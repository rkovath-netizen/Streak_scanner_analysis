import requests
import pandas as pd
from datetime import datetime
import pytz

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
UPSTOX_HISTORICAL_URL = "https://api.upstox.com/v2/historical-candle/{instrument_key}/{unit}/{to_date}/{from_date}"

_INSTRUMENT_DF_CACHE = None

def load_upstox_master(ui_log):
    global _INSTRUMENT_DF_CACHE
    if _INSTRUMENT_DF_CACHE is not None: return _INSTRUMENT_DF_CACHE
    try:
        ui_log("Downloading Upstox F&O Master list...")
        df = pd.read_csv(UPSTOX_INSTRUMENT_URL, compression='gzip')
        df = df[df['exchange'] == 'NSE_FO']
        df['expiry'] = pd.to_datetime(df['expiry'], errors='coerce')
        _INSTRUMENT_DF_CACHE = df
        ui_log(f"✅ Loaded {len(df)} F&O contracts.")
        return df
    except Exception as e:
        ui_log(f"❌ Failed to load Master list: {e}")
        return pd.DataFrame()

def get_atm_option_instrument(cash_symbol, signal_time, cash_ltp, opt_type, ui_log):
    df = load_upstox_master(ui_log)
    if df.empty: return None, None
    
    signal_date = pd.to_datetime(signal_time).date()
    opts = df[(df['name'] == cash_symbol) & (df['instrument_type'] == 'OPTSTK') & (df['option_type'] == opt_type)]
    
    if opts.empty:
        ui_log(f"[{cash_symbol}] ❌ Not found in F&O Master.")
        return None, None

    future_expiries = opts[opts['expiry'].dt.date >= signal_date]
    if future_expiries.empty:
        ui_log(f"[{cash_symbol}] ❌ No {opt_type} expiries found after {signal_date}.")
        return None, None
        
    nearest_expiry = future_expiries['expiry'].min()
    current_expiry_opts = future_expiries[future_expiries['expiry'] == nearest_expiry].copy()
    current_expiry_opts.loc[:, 'strike_diff'] = abs(current_expiry_opts['strike'] - float(cash_ltp))
    atm_row = current_expiry_opts.sort_values(by='strike_diff').iloc[0]
    
    ui_log(f"[{cash_symbol}] ✅ Mapped to Option: {atm_row['tradingsymbol']}")
    return atm_row['instrument_key'], atm_row['tradingsymbol']

def fetch_upstox_intraday_candles(instrument_key, start_dt, end_dt, access_token, ui_log, interval="15minute"):
    to_date_str = end_dt.strftime("%Y-%m-%d")
    from_date_str = start_dt.strftime("%Y-%m-%d")
    url = UPSTOX_HISTORICAL_URL.format(instrument_key=instrument_key, unit=interval, to_date=to_date_str, from_date=from_date_str)
    headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            candles = data.get("data", {}).get("candles", [])
            if not candles:
                ui_log(f"[{instrument_key}] ❌ API 200 OK, but 0 candles returned for {from_date_str} to {to_date_str}")
                return pd.DataFrame()

            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            ist = pytz.timezone("Asia/Kolkata")
            df['timestamp'] = df['timestamp'].dt.tz_convert(ist).dt.tz_localize(None)
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        else:
            ui_log(f"[{instrument_key}] ❌ HTTP {response.status_code}: {response.text}")
    except Exception as e:
        ui_log(f"[{instrument_key}] ❌ Fetch Exception: {e}")
        
    return pd.DataFrame()
