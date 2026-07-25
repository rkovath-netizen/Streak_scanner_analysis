import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz

UPSTOX_INSTRUMENT_URL = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
UPSTOX_HISTORICAL_URL = "https://api.upstox.com/v2/historical-candle/{instrument_key}/{unit}/{to_date}/{from_date}"

_INSTRUMENT_MAP_CACHE = None

def get_instrument_map():
    """Downloads and caches Upstox instrument master to map symbols to instrument keys."""
    global _INSTRUMENT_MAP_CACHE
    if _INSTRUMENT_MAP_CACHE is not None:
        return _INSTRUMENT_MAP_CACHE

    try:
        df = pd.read_csv(UPSTOX_INSTRUMENT_URL, compression='gzip')
        # Filter for NSE Equities
        nse_df = df[(df['exchange'] == 'NSE_EQ') & (df['instrument_type'] == 'EQUITY')]
        
        # Create a dictionary mapping trading_symbol to instrument_key
        _INSTRUMENT_MAP_CACHE = dict(zip(nse_df['tradingsymbol'], nse_df['instrument_key']))
        return _INSTRUMENT_MAP_CACHE
    except Exception as e:
        print(f"[ERROR] Failed to load Upstox instrument master: {e}")
        return {}

def fetch_upstox_intraday_candles(symbol, start_dt, end_dt, access_token, interval="15minute"):
    """
    Fetches historical candle data from Upstox API v2.
    
    Parameters:
        symbol (str): Clean stock symbol (e.g., 'WAAREEENER', 'RELIANCE')
        start_dt (datetime): Start datetime
        end_dt (datetime): End datetime
        access_token (str): Upstox access token
        interval (str): Candle timeframe ('15minute', '1minute', 'day')
    """
    instrument_map = get_instrument_map()
    
    # Strip prefixes if any
    clean_sym = symbol.replace("NSE:", "").replace("BSE:", "").strip()
    instrument_key = instrument_map.get(clean_sym)
    
    if not instrument_key:
        print(f"[WARNING] Symbol '{clean_sym}' not found in Upstox instrument map.")
        return pd.DataFrame()

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

    print(f"[DEBUG] Fetching Upstox candles for {clean_sym} ({from_date_str} to {to_date_str})...")

    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            data = response.json()
            candles = data.get("data", {}).get("candles", [])
            
            if not candles:
                print(f"[WARNING] No candle data returned for {clean_sym}.")
                return pd.DataFrame()

            # Upstox candle schema: [timestamp, open, high, low, close, volume, open_interest]
            df = pd.DataFrame(candles, columns=["timestamp", "open", "high", "low", "close", "volume", "oi"])
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            
            # Convert to IST timezone
            ist = pytz.timezone("Asia/Kolkata")
            df['timestamp'] = df['timestamp'].dt.tz_convert(ist).dt.tz_localize(None)
            
            df = df.sort_values("timestamp").reset_index(drop=True)
            return df
        else:
            print(f"[ERROR] Upstox API Error ({response.status_code}): {response.text}")
            return pd.DataFrame()

    except Exception as e:
        print(f"[ERROR] Exception during Upstox fetch for {clean_sym}: {e}")
        return pd.DataFrame()
