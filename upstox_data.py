import requests
import pandas as pd
from datetime import timedelta
import pytz

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
UPSTOX_HISTORICAL_URL = "https://api.upstox.com/v2/historical-candle/{instrument_key}/{unit}/{to_date}/{from_date}"

_INSTRUMENT_DF_CACHE = None

def get_instrument_df():
    """Downloads and caches the FULL Upstox instrument master for Equity & Options."""
    global _INSTRUMENT_DF_CACHE
    if _INSTRUMENT_DF_CACHE is not None:
        return _INSTRUMENT_DF_CACHE

    try:
        print("[DEBUG] Downloading Upstox Instrument Master. This takes a few seconds...")
        df = pd.read_csv(UPSTOX_INSTRUMENT_URL, compression='gzip')
        # Filter for NSE Equities and NSE F&O (Options)
        df = df[df['exchange'].isin(['NSE_EQ', 'NSE_FO'])]
        
        # Convert expiry to datetime for easy option chain filtering
        df['expiry'] = pd.to_datetime(df['expiry'], errors='coerce')
        
        _INSTRUMENT_DF_CACHE = df
        return _INSTRUMENT_DF_CACHE
    except Exception as e:
        print(f"[ERROR] Failed to load Upstox instrument master: {e}")
        return pd.DataFrame()

def get_nfo_lot_size(symbol):
    """Fetches the actual F&O lot size for the given symbol (e.g. NIFTY = 25)."""
    df = get_instrument_df()
    derivatives = df[(df['name'] == symbol) & (df['exchange'] == 'NSE_FO')]
    if not derivatives.empty:
        return int(derivatives.iloc[0]['lot_size'])
    return 1 # Fallback to 1 if not an F&O stock

def fetch_upstox_intraday_candles(symbol_or_key, start_dt, end_dt, access_token, interval="15minute", is_key=False):
    """Fetches historical candle data. Accepts trading symbol or direct instrument_key."""
    df_inst = get_instrument_df()
    
    if not is_key:
        clean_sym = symbol_or_key.replace("NSE:", "").replace("BSE:", "").strip()
        eq_rows = df_inst[(df_inst['tradingsymbol'] == clean_sym) & (df_inst['exchange'] == 'NSE_EQ')]
        if eq_rows.empty:
            print(f"[WARNING] Symbol '{clean_sym}' not found.")
            return pd.DataFrame()
        instrument_key = eq_rows.iloc[0]['instrument_key']
    else:
        instrument_key = symbol_or_key

    to_date_str = end_dt.strftime("%Y-%m-%d")
    from_date_str = start_dt.strftime("%Y-%m-%d")

    url = UPSTOX_HISTORICAL_URL.format(
        instrument_key=instrument_key,
        unit=interval,
        to_date=to_date_str,
        from_date=from_date_str
    )

    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                return pd.DataFrame()

            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            ist = pytz.timezone("Asia/Kolkata")
            df['timestamp'] = df['timestamp'].dt.tz_convert(ist).dt.tz_localize(None)
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        else:
            return pd.DataFrame()
    except Exception as e:
        print(f"[ERROR] API fetch exception: {e}")
        return pd.DataFrame()

def get_option_legs(symbol, entry_time, entry_price, strategy):
    """Finds the instrument keys for ATM, OTM1, and OTM2 for the current expiry."""
    df = get_instrument_df()
    
    # Filter valid options for this underlying
    opts = df[(df['name'] == symbol) & (df['instrument_type'].isin(['OPTSTK', 'OPTIDX']))].copy()
    if opts.empty:
        return []
    
    # Find closest upcoming expiry
    future_opts = opts[opts['expiry'].dt.date >= entry_time.date()]
    if future_opts.empty:
        return []
    closest_expiry = future_opts['expiry'].min()
    current_chain = future_opts[future_opts['expiry'] == closest_expiry]

    # Find ATM strike
    unique_strikes = sorted(current_chain['strike'].unique())
    if not unique_strikes:
        return []
        
    closest_strike_idx = min(range(len(unique_strikes)), key=lambda i: abs(unique_strikes[i] - entry_price))
    
    try:
        atm_strike = unique_strikes[closest_strike_idx]
        otm1_pe_strike = unique_strikes[closest_strike_idx - 1] if closest_strike_idx - 1 >= 0 else atm_strike
        otm2_pe_strike = unique_strikes[closest_strike_idx - 2] if closest_strike_idx - 2 >= 0 else otm1_pe_strike
        otm1_ce_strike = unique_strikes[closest_strike_idx + 1] if closest_strike_idx + 1 < len(unique_strikes) else atm_strike
        otm2_ce_strike = unique_strikes[closest_strike_idx + 2] if closest_strike_idx + 2 < len(unique_strikes) else otm1_ce_strike
    except IndexError:
        return [] # Fallback if strikes are weirdly formatted

    def get_key(strike, opt_type):
        leg_row = current_chain[(current_chain['strike'] == strike) & (current_chain['instrument_type'] == opt_type)]
        return leg_row.iloc[0]['instrument_key'] if not leg_row.empty else None

    legs = []
    if strategy == "Options: Long Straddle":
        legs.append({'key': get_key(atm_strike, 'CE'), 'type': 'ATM CE', 'side': 1})
        legs.append({'key': get_key(atm_strike, 'PE'), 'type': 'ATM PE', 'side': 1})
    elif strategy == "Options: Bull Put Spread (ATM & OTM1)":
        legs.append({'key': get_key(atm_strike, 'PE'), 'type': 'ATM PE', 'side': -1})
        legs.append({'key': get_key(otm1_pe_strike, 'PE'), 'type': 'OTM1 PE', 'side': 1})
    elif strategy == "Options: Bull Put Spread (ATM & OTM2)":
        legs.append({'key': get_key(atm_strike, 'PE'), 'type': 'ATM PE', 'side': -1})
        legs.append({'key': get_key(otm2_pe_strike, 'PE'), 'type': 'OTM2 PE', 'side': 1})
    elif strategy == "Options: Bear Call Spread (ATM & OTM1)":
        legs.append({'key': get_key(atm_strike, 'CE'), 'type': 'ATM CE', 'side': -1})
        legs.append({'key': get_key(otm1_ce_strike, 'CE'), 'type': 'OTM1 CE', 'side': 1})
    elif strategy == "Options: Bear Call Spread (ATM & OTM2)":
        legs.append({'key': get_key(atm_strike, 'CE'), 'type': 'ATM CE', 'side': -1})
        legs.append({'key': get_key(otm2_ce_strike, 'CE'), 'type': 'OTM2 CE', 'side': 1})
        
    return [l for l in legs if l['key'] is not None]
