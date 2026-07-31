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
        df = pd.read_csv(UPSTOX_INSTRUMENT_URL, compression='gzip')
        df = df[df['exchange'] == 'NSE_FO']
        df['expiry'] = pd.to_datetime(df['expiry'], errors='coerce')
        _INSTRUMENT_DF_CACHE = df
        ui_log(f"✅ Loaded {len(df)} F&O contracts from Upstox Master.")
        return df
    except Exception as e:
        ui_log(f"❌ Failed to load Master list: {e}")
        return pd.DataFrame()

def get_atm_option_instrument(cash_symbol, signal_time, cash_ltp, opt_type, ui_log):
    df = load_upstox_master(ui_log)
    if df.empty: 
        return None, None, "Master List Empty"
    
    # Standardize symbol (remove exchange prefixes, spaces, hyphens for flexible matching)
    clean_sym = cash_symbol.replace("NSE:", "").replace("BSE:", "").strip()
    raw_sym_no_hyphen = clean_sym.replace("-", "").replace("_", "").replace("&", "")
    signal_date = pd.to_datetime(signal_time).date()
    
    if float(cash_ltp) <= 0:
        ui_log(f"[{clean_sym}] ⚠️ Cash LTP is {cash_ltp}. Cannot compute ATM strike.")
        return None, None, "LTP is 0.0 or Invalid"

    # Filter for OPTSTK and option type (CE/PE)
    opts = df[(df['instrument_type'] == 'OPTSTK') & (df['option_type'] == opt_type)].copy()
    
    # Clean Upstox names for flexible matching (e.g., handles NUVAMA, BAJAJ-AUTO, M&M)
    opts['clean_name'] = opts['name'].astype(str).str.replace("-", "").str.replace("_", "").str.replace("&", "").str.strip()
    opts['clean_trade'] = opts['tradingsymbol'].astype(str).str.replace("-", "").str.replace("_", "").str.replace("&", "").str.strip()

    # Search match
    matched_opts = opts[
        (opts['name'] == clean_sym) | 
        (opts['clean_name'] == raw_sym_no_hyphen) | 
        (opts['tradingsymbol'].str.startswith(clean_sym)) |
        (opts['clean_trade'].str.startswith(raw_sym_no_hyphen))
    ]
    
    if matched_opts.empty:
        ui_log(f"[{clean_sym}] ❌ Not found in Upstox F&O Master.")
        return None, None, "Symbol Not Found in F&O Master"

    # Filter for expiries ON or AFTER signal date
    future_expiries = matched_opts[matched_opts['expiry'].dt.date >= signal_date]
    if future_expiries.empty:
        ui_log(f"[{clean_sym}] ❌ No active {opt_type} expiries found after {signal_date}.")
        return None, None, f"No Expiries >= {signal_date}"
        
    nearest_expiry = future_expiries['expiry'].min()
    current_expiry_opts = future_expiries[future_expiries['expiry'] == nearest_expiry].copy()
    
    # Calculate ATM Strike
    current_expiry_opts.loc[:, 'strike_diff'] = abs(current_expiry_opts['strike'] - float(cash_ltp))
    atm_row = current_expiry_opts.sort_values(by='strike_diff').iloc[0]
    
    ui_log(f"[{clean_sym}] ✅ Mapped cash {cash_ltp} -> ATM Option: {atm_row['tradingsymbol']}")
    return atm_row['instrument_key'], atm_row['tradingsymbol'], "Success"

def fetch_upstox_intraday_candles(instrument_key, start_dt, end_dt, access_token, ui_log, interval="15minute"):
    to_date_str = end_dt.strftime("%Y-%m-%d")
    from_date_str = start_dt.strftime("%Y-%m-%d")
    fetch_unit = "1minute" if interval == "15minute" else interval
    
    url = UPSTOX_HISTORICAL_URL.format(
        instrument_key=instrument_key, 
        unit=fetch_unit, 
        to_date=to_date_str, 
        from_date=from_date_str
    )
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code == 200:
            data = response.json()
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                ui_log(f"[{instrument_key}] ❌ API 200 OK, but 0 candles returned ({from_date_str} to {to_date_str}).")
                return pd.DataFrame()

            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            ist = pytz.timezone("Asia/Kolkata")
            df['timestamp'] = df['timestamp'].dt.tz_convert(ist).dt.tz_localize(None)
            df = df.sort_values("timestamp").reset_index(drop=True)
            
            # Resample 1-min to 15-min
            if interval == "15minute":
                df.set_index('timestamp', inplace=True)
                ohlc_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum', 'oi': 'last'}
                df = df.resample('15min', closed='left', label='left').agg(ohlc_dict).dropna()
                df.reset_index(inplace=True)
                
            return df
        else:
            ui_log(f"[{instrument_key}] ❌ HTTP {response.status_code}: {response.text}")
    except Exception as e:
        ui_log(f"[{instrument_key}] ❌ Fetch Exception: {e}")
        
    return pd.DataFrame()
