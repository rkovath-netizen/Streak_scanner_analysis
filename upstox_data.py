import requests
import pandas as pd
from datetime import datetime
import pytz

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
UPSTOX_HISTORICAL_URL = "https://api.upstox.com/v2/historical-candle/{instrument_key}/{unit}/{to_date}/{from_date}"

_INSTRUMENT_DF_CACHE = None

def load_upstox_master(ui_log):
    global _INSTRUMENT_DF_CACHE
    if _INSTRUMENT_DF_CACHE is not None: 
        return _INSTRUMENT_DF_CACHE
    try:
        ui_log("Downloading Upstox F&O Master list...")
        # Download the compressed CSV directly from Upstox
        df = pd.read_csv(UPSTOX_INSTRUMENT_URL, compression='gzip')
        
        # We need NSE_FO for options.
        df = df[df['exchange'] == 'NSE_FO']
        
        # Convert expiry to datetime for easy filtering
        df['expiry'] = pd.to_datetime(df['expiry'], errors='coerce')
        _INSTRUMENT_DF_CACHE = df
        ui_log(f"✅ Loaded {len(df)} F&O contracts.")
        return df
    except Exception as e:
        ui_log(f"❌ Failed to load Master list: {e}")
        return pd.DataFrame()

def get_atm_option_instrument(cash_symbol, signal_time, cash_ltp, opt_type, ui_log):
    df = load_upstox_master(ui_log)
    if df.empty: 
        return None, None
    
    # Clean the symbol from Zerodha (e.g., 'NSE:BOSCHLTD' -> 'BOSCHLTD')
    clean_sym = cash_symbol.replace("NSE:", "").replace("BSE:", "").strip()
    signal_date = pd.to_datetime(signal_time).date()
    
    # 1. Broad Search Strategy
    # Upstox usually puts the underlying symbol in the 'name' column OR at the start of 'tradingsymbol'
    # We filter for OPTSTK (Stock Options) and the correct CE/PE type.
    opts = df[
        (df['instrument_type'] == 'OPTSTK') & 
        (df['option_type'] == opt_type)
    ]
    
    # Filter where 'name' matches OR 'tradingsymbol' starts with the symbol
    opts = opts[
        (opts['name'] == clean_sym) | 
        (opts['tradingsymbol'].str.startswith(clean_sym))
    ]
    
    if opts.empty:
        ui_log(f"[{clean_sym}] ❌ Not found in F&O Master via name or tradingsymbol.")
        return None, None

    # 2. Find Next Expiry
    # Filter for expiries that are ON or AFTER the signal date
    future_expiries = opts[opts['expiry'].dt.date >= signal_date]
    
    if future_expiries.empty:
        ui_log(f"[{clean_sym}] ❌ No {opt_type} expiries found on or after {signal_date}.")
        return None, None
        
    # Get the closest expiry date
    nearest_expiry = future_expiries['expiry'].min()
    current_expiry_opts = future_expiries[future_expiries['expiry'] == nearest_expiry].copy()
    
    # 3. Find ATM Strike
    # Calculate difference between the strike price and the cash signal price
    current_expiry_opts.loc[:, 'strike_diff'] = abs(current_expiry_opts['strike'] - float(cash_ltp))
    
    # Sort by the smallest difference to get the At-The-Money (ATM) contract
    atm_row = current_expiry_opts.sort_values(by='strike_diff').iloc[0]
    
    ui_log(f"[{clean_sym}] ✅ Mapped cash {cash_ltp} to ATM Option: {atm_row['tradingsymbol']}")
    return atm_row['instrument_key'], atm_row['tradingsymbol']

def fetch_upstox_intraday_candles(instrument_key, start_dt, end_dt, access_token, ui_log, interval="15minute"):
    to_date_str = end_dt.strftime("%Y-%m-%d")
    from_date_str = start_dt.strftime("%Y-%m-%d")
    
    url = UPSTOX_HISTORICAL_URL.format(
        instrument_key=instrument_key, 
        unit=interval, 
        to_date=to_date_str, 
        from_date=from_date_str
    )
    
    headers = {
        "Accept": "application/json", 
        "Authorization": f"Bearer {access_token}"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            candles = data.get("data", {}).get("candles", [])
            
            if not candles:
                ui_log(f"[{instrument_key}] ❌ API 200 OK, but 0 candles returned for {from_date_str} to {to_date_str}")
                return pd.DataFrame()

            # Upstox returns: [timestamp, open, high, low, close, volume, open_interest]
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Convert timezone to IST and remove timezone awareness for easier comparison
            ist = pytz.timezone("Asia/Kolkata")
            df['timestamp'] = df['timestamp'].dt.tz_convert(ist).dt.tz_localize(None)
            
            # Sort chronologically
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        else:
            ui_log(f"[{instrument_key}] ❌ HTTP {response.status_code}: {response.text}")
            
    except Exception as e:
        ui_log(f"[{instrument_key}] ❌ Fetch Exception: {e}")
        
    return pd.DataFrame()
