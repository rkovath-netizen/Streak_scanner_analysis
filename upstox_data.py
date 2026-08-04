import requests
import pandas as pd
import pytz
import streamlit as st
import urllib.parse
from datetime import datetime

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
UPSTOX_HISTORICAL_URL = "https://api.upstox.com/v2/historical-candle/{instrument_key}/{unit}/{to_date}/{from_date}"

@st.cache_data(ttl=3600, show_spinner=False)
def get_instrument_df():
    try:
        df = pd.read_csv(UPSTOX_INSTRUMENT_URL, compression='gzip')
        df = df[df['exchange'].isin(['NSE_EQ', 'NSE_FO'])]
        return df
    except Exception as e:
        st.error(f"❌ Failed to download Upstox Instrument Master: {e}")
        return pd.DataFrame()

def get_nfo_lot_size(symbol):
    df = get_instrument_df()
    if df.empty: return 1
    derivatives = df[(df['name'] == symbol) & (df['exchange'] == 'NSE_FO')]
    if not derivatives.empty: return int(derivatives.iloc[0]['lot_size'])
    return 1 

def fetch_upstox_intraday_candles(symbol_or_key, start_dt, end_dt, access_token, interval="1minute", is_key=False, log_func=print):
    df_inst = get_instrument_df()
    if df_inst.empty:
        log_func("⚠️ Instrument master is empty.")
        return pd.DataFrame()

    if not is_key:
        clean_sym = symbol_or_key.replace("NSE:", "").replace("BSE:", "").strip()
        eq_rows = df_inst[(df_inst['tradingsymbol'] == clean_sym) & (df_inst['exchange'] == 'NSE_EQ')]
        if eq_rows.empty:
            log_func(f"⚠️ Symbol '{clean_sym}' not found in Upstox Master.")
            return pd.DataFrame()
        instrument_key = eq_rows.iloc[0]['instrument_key']
    else:
        instrument_key = symbol_or_key

    # Safe URL Encoding to prevent HTTP 400 Bad Request
    safe_instrument_key = urllib.parse.quote(instrument_key)

    current_date = datetime.now(pytz.timezone("Asia/Kolkata")).replace(tzinfo=None)
    if end_dt > current_date:
        end_dt = current_date
    if start_dt > current_date:
        return pd.DataFrame()

    url = UPSTOX_HISTORICAL_URL.format(
        instrument_key=safe_instrument_key, 
        unit=interval,
        to_date=end_dt.strftime("%Y-%m-%d"), 
        from_date=start_dt.strftime("%Y-%m-%d")
    )
    
    try:
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            candles = response.json().get("data", {}).get("candles", [])
            if not candles:
                return pd.DataFrame()
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
            df['timestamp'] = pd.to_datetime(df['timestamp']).dt.tz_convert(pytz.timezone("Asia/Kolkata")).dt.tz_localize(None)
            return df.sort_values("timestamp").reset_index(drop=True)
        else:
            log_func(f"❌ Upstox API Error HTTP {response.status_code} for {instrument_key}")
            return pd.DataFrame()
    except Exception as e:
        log_func(f"❌ Exception fetching candles: {e}")
        return pd.DataFrame()

def get_option_legs(symbol, entry_time, entry_price, strategy):
    df = get_instrument_df()
    if df.empty: return []
    
    # 1. Broad filter: Grab ALL F&O instruments for this specific stock
    opts = df[(df['name'] == symbol) & (df['exchange'] == 'NSE_FO')].copy()
    if opts.empty: return []
    
    # 2. Strict type conversions so math operations don't fail
    opts['strike'] = pd.to_numeric(opts['strike'], errors='coerce')
    opts = opts.dropna(subset=['strike'])
    
    opts['expiry_date'] = pd.to_datetime(opts['expiry'], errors='coerce').dt.date
    opts = opts.dropna(subset=['expiry_date'])
    
    entry_date = pd.to_datetime(entry_time).date()
    
    # 3. Find the current chain
    future_opts = opts[opts['expiry_date'] >= entry_date]
    if future_opts.empty: return []
    
    closest_expiry = future_opts['expiry_date'].min()
    current_chain = future_opts[future_opts['expiry_date'] == closest_expiry]

    unique_strikes = sorted(current_chain['strike'].unique())
    if not unique_strikes: return []
    
    closest_idx = min(range(len(unique_strikes)), key=lambda i: abs(unique_strikes[i] - entry_price))
    
    try:
        atm = unique_strikes[closest_idx]
        otm1_pe = unique_strikes[max(0, closest_idx - 1)]
        otm2_pe = unique_strikes[max(0, closest_idx - 2)]
        otm1_ce = unique_strikes[min(len(unique_strikes)-1, closest_idx + 1)]
        otm2_ce = unique_strikes[min(len(unique_strikes)-1, closest_idx + 2)]
    except IndexError:
        return [] 

    def get_key(s, opt_type):
        leg = current_chain[(current_chain['strike'] == s) & (current_chain['tradingsymbol'].astype(str).str.endswith(opt_type))]
        return leg.iloc[0]['instrument_key'] if not leg.empty else None

    legs = []
    if strategy == "Options: Naked Call Buy": legs.append({'type': 'ATM CE', 'key': get_key(atm, 'CE'), 'side': 1})
    elif strategy == "Options: Naked Put Buy": legs.append({'type': 'ATM PE', 'key': get_key(atm, 'PE'), 'side': 1})
    elif strategy == "Options: Long Straddle":
        legs.append({'type': 'ATM CE', 'key': get_key(atm, 'CE'), 'side': 1})
        legs.append({'type': 'ATM PE', 'key': get_key(atm, 'PE'), 'side': 1})
    elif strategy == "Options: Bull Put Spread (ATM & OTM1)":
        legs.append({'type': 'ATM PE', 'key': get_key(atm, 'PE'), 'side': -1}); legs.append({'type': 'OTM1 PE', 'key': get_key(otm1_pe, 'PE'), 'side': 1})
    elif strategy == "Options: Bull Put Spread (ATM & OTM2)":
        legs.append({'type': 'ATM PE', 'key': get_key(atm, 'PE'), 'side': -1}); legs.append({'type': 'OTM2 PE', 'key': get_key(otm2_pe, 'PE'), 'side': 1})
    elif strategy == "Options: Bear Call Spread (ATM & OTM1)":
        legs.append({'type': 'ATM CE', 'key': get_key(atm, 'CE'), 'side': -1}); legs.append({'type': 'OTM1 CE', 'key': get_key(otm1_ce, 'CE'), 'side': 1})
    elif strategy == "Options: Bear Call Spread (ATM & OTM2)":
        legs.append({'type': 'ATM CE', 'key': get_key(atm, 'CE'), 'side': -1}); legs.append({'type': 'OTM2 CE', 'key': get_key(otm2_ce, 'CE'), 'side': 1})
        
    return [l for l in legs if l['key'] is not None]
