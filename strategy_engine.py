import pandas as pd
from datetime import timedelta
from upstox_data import fetch_upstox_intraday_candles

def process_streak_batch(csv_files, upstox_token, strategy_type="long", tp_pct=0.05, sl_pct=0.03, max_hold_days=5, progress_callback=None):
    """
    Parses multiple Streak CSV files and simulates exit logic for multi-day swing trades.
    Uses 15-min candles across the 5-day holding period to capture exact TP/SL hits and overnight gaps.
    """
    all_signals = []
    
    for file in csv_files:
        df = pd.read_csv(file)
        all_signals.append(df)
        
    if not all_signals:
        return pd.DataFrame()

    combined_df = pd.concat(all_signals, ignore_index=True)
    combined_df['time'] = pd.to_datetime(combined_df['time'])
    
    trade_results = []
    total_trades = len(combined_df)

    for idx, row in combined_df.iterrows():
        raw_symbol = row['seg_sym']
        entry_time = row['time']
        entry_price = float(row['ltp'])
        clean_symbol = raw_symbol.replace("NSE:", "").replace("BSE:", "").strip()

        if progress_callback:
            progress_callback(idx + 1, total_trades, f"Processing Swing Trade for {clean_symbol} at {entry_time}")

        # Set TP/SL Thresholds
        if strategy_type == "long":
            target_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
        else: # Short setup
            target_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)

        # Fetch 15-min candles spanning the next 10 calendar days (to guarantee 5 active trading days)
        fetch_start = entry_time
        fetch_end = entry_time + timedelta(days=10) 

        candles_df = fetch_upstox_intraday_candles(
            symbol=clean_symbol,
            start_dt=fetch_start,
            end_dt=fetch_end,
            access_token=upstox_token,
            interval="15minute"
        )

        if candles_df.empty:
            continue

        # Keep only candles that occurred on or after the entry timestamp
        candles_df = candles_df[candles_df['timestamp'] >= entry_time].reset_index(drop=True)
        if candles_df.empty:
            continue

        exit_price, exit_time, exit_reason = None, None, None
        bars_in_trade = 0
        unique_trading_days = []

        # Candle-by-candle Swing Simulation
        for i, candle in candles_df.iterrows():
            bars_in_trade += 1
            c_time = candle['timestamp']
            c_date = c_time.date()
            open_p, high_p, low_p, close_p = candle['open'], candle['high'], candle['low'], candle['close']

            # Track unique days the stock is held overnight
            if c_date not in unique_trading_days:
                unique_trading_days.append(c_date)
                
                # --- MARKET OPEN GAP HANDLING (For days 2, 3, 4, 5) ---
                if len(unique_trading_days) > 1:
                    if strategy_type == "long":
                        if open_p >= target_price:
                            exit_price = open_p # Gap up profit!
                            exit_time = c_time
                            exit_reason = f"Target Hit on Gap-Up Open"
                            break
                        elif open_p <= sl_price:
                            exit_price = open_p # Gap down loss (Slippage)
                            exit_time = c_time
                            exit_reason = f"SL Hit on Gap-Down Open"
                            break
                    else: # Short setup gap handling
                        if open_p <= target_price:
                            exit_price = open_p # Gap down profit!
                            exit_time = c_time
                            exit_reason = f"Target Hit on Gap-Down Open"
                            break
                        elif open_p >= sl_price:
                            exit_price = open_p # Gap up loss (Slippage)
                            exit_time = c_time
                            exit_reason = f"SL Hit on Gap-Up Open"
                            break

            # --- 5-DAY HARD EXIT TRIGGER ---
            # If we enter a 6th trading day, we must hard exit at the market Open price
            if len(unique_trading_days) > max_hold_days:
                exit_price = open_p
                exit_time = c_time
                exit_reason = f"Time Exit (Held {max_hold_days} Days)"
                break

            # --- INTRADAY PRICE ACTION CHECK ---
            if strategy_type == "long":
                if high_p >= target_price:
                    exit_price = target_price
                    exit_time = c_time
                    exit_reason = f"Target Hit (+{tp_pct*100:.1f}%)"
                    break
                elif low_p <= sl_price:
                    exit_price = sl_price
                    exit_time = c_time
                    exit_reason = f"SL Hit (-{sl_pct*100:.1f}%)"
                    break
            else: # Short setup logic
                if low_p <= target_price:
                    exit_price = target_price
                    exit_time = c_time
                    exit_reason = f"Target Hit (+{tp_pct*100:.1f}%)"
                    break
                elif high_p >= sl_price:
                    exit_price = sl_price
                    exit_time = c_time
                    exit_reason = f"SL Hit (-{sl_pct*100:.1f}%)"
                    break

        # Fallback if the trade is still open at the end of the fetched historical data
        if exit_price is None:
            last_candle = candles_df.iloc[-1]
            exit_price = last_candle['close']
            exit_time = last_candle['timestamp']
            exit_reason = f"Data Ended (Holding Day {len(unique_trading_days)})"

        # Calculate final Absolute and % PnL based on direction
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
            'days_held': len(unique_trading_days),
            'bars_in_trade': bars_in_trade,
            'exit_reason': exit_reason
        })

    return pd.DataFrame(trade_results)
