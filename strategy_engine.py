import pandas as pd
from datetime import timedelta
from upstox_data import fetch_upstox_intraday_candles

def process_streak_batch(csv_files, upstox_token, strategy_type="long", tp_pct=0.05, sl_pct=0.03, max_hold_days=5, progress_callback=None):
    """
    Parses multiple Streak CSV files and simulates exit logic candle by candle.
    """
    all_signals = []
    
    # 1. Load and combine uploaded Streak CSVs
    for file in csv_files:
        df = pd.read_csv(file)
        all_signals.append(df)
        
    if not all_signals:
        return pd.DataFrame()

    combined_df = pd.concat(all_signals, ignore_index=True)
    combined_df['time'] = pd.to_datetime(combined_df['time'])
    
    trade_results = []
    total_trades = len(combined_df)
    
    print(f"[INFO] Loaded {total_trades} signals from {len(csv_files)} files.")

    # 2. Iterate through each trade signal
    for idx, row in combined_df.iterrows():
        raw_symbol = row['seg_sym']
        entry_time = row['time']
        entry_price = float(row['ltp'])
        
        clean_symbol = raw_symbol.replace("NSE:", "").replace("BSE:", "").strip()

        if progress_callback:
            progress_callback(idx + 1, total_trades, f"Processing {clean_symbol} at {entry_time}")

        # Define targets and stop loss
        if strategy_type == "long":
            target_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
        else: # Short setup
            target_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)

        # Fetch candles covering the holding period
        fetch_start = entry_time
        fetch_end = entry_time + timedelta(days=max_hold_days + 5) # Buffer for weekends/holidays

        candles_df = fetch_upstox_intraday_candles(
            symbol=clean_symbol,
            start_dt=fetch_start,
            end_dt=fetch_end,
            access_token=upstox_token,
            interval="15minute"
        )

        if candles_df.empty:
            print(f"[SKIP] No intraday data for {clean_symbol} on {entry_time}")
            continue

        # Filter candles after signal timestamp
        candles_df = candles_df[candles_df['timestamp'] >= entry_time].reset_index(drop=True)
        
        if candles_df.empty:
            continue

        exit_price, exit_time, exit_reason = None, None, None
        bars_in_trade = 0
        unique_dates = []

        # Candle-by-candle simulation
        for i, candle in candles_df.iterrows():
            bars_in_trade += 1
            c_time = candle['timestamp']
            c_date = c_time.date()

            if c_date not in unique_dates:
                unique_dates.append(c_date)

            # Check Hard Exit after N trading days
            if len(unique_dates) > max_hold_days:
                exit_price = candle['open']
                exit_time = c_time
                exit_reason = f"Time Exit ({max_hold_days} Days)"
                break

            high, low = candle['high'], candle['low']

            if strategy_type == "long":
                if high >= target_price:
                    exit_price = target_price
                    exit_time = c_time
                    exit_reason = f"Target Hit (+{tp_pct*100:.1f}%)"
                    break
                elif low <= sl_price:
                    exit_price = sl_price
                    exit_time = c_time
                    exit_reason = f"SL Hit (-{sl_pct*100:.1f}%)"
                    break
            else: # Short setup logic
                if low <= target_price:
                    exit_price = target_price
                    exit_time = c_time
                    exit_reason = f"Target Hit (+{tp_pct*100:.1f}%)"
                    break
                elif high >= sl_price:
                    exit_price = sl_price
                    exit_time = c_time
                    exit_reason = f"SL Hit (-{sl_pct*100:.1f}%)"
                    break

        # Fallback if trade remains open at end of data window
        if exit_price is None:
            last_candle = candles_df.iloc[-1]
            exit_price = last_candle['close']
            exit_time = last_candle['timestamp']
            exit_reason = "Data Ended (Open Position)"

        # Calculate PnL
        if strategy_type == "long":
            pnl_abs = exit_price - entry_price
        else:
            pnl_abs = entry_price - exit_price

        pnl_pct = (pnl_abs / entry_price) * 100

        trade_results.append({
            'symbol': clean_symbol,
            'entry_date': entry_time.strftime("%Y-%m-%d"),
            'entry_time': entry_time.strftime("%H:%M:%S"),
            'entry_price': round(entry_price, 2),
            'exit_date': exit_time.strftime("%Y-%m-%d"),
            'exit_time': exit_time.strftime("%H:%M:%S"),
            'exit_price': round(exit_price, 2),
            'pnl_abs': round(pnl_abs, 2),
            'pnl_pct': round(pnl_pct, 2),
            'bars_in_trade': bars_in_trade,
            'exit_reason': exit_reason
        })

    return pd.DataFrame(trade_results)
