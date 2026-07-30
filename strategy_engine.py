import pandas as pd
from datetime import timedelta
from upstox_data import fetch_upstox_intraday_candles

def process_streak_batch(csv_files, upstox_token, strategy_type, tp_pct, sl_pct, max_hold_days, progress_callback):
    all_signals = [pd.read_csv(f) for f in csv_files]
    if not all_signals: return pd.DataFrame()

    combined_df = pd.concat(all_signals, ignore_index=True)
    combined_df['time'] = pd.to_datetime(combined_df['time'])
    
    trade_results = []
    total_trades = len(combined_df)

    for idx, row in combined_df.iterrows():
        clean_symbol = row['seg_sym'].replace("NSE:", "").replace("BSE:", "").strip()
        entry_time = row['time']
        entry_price = float(row['ltp'])

        if progress_callback:
            progress_callback(idx + 1, total_trades, f"Processing {clean_symbol}")

        if strategy_type == "long":
            target_price = entry_price * (1 + tp_pct)
            sl_price = entry_price * (1 - sl_pct)
        else:
            target_price = entry_price * (1 - tp_pct)
            sl_price = entry_price * (1 + sl_pct)

        fetch_start = entry_time
        fetch_end = entry_time + timedelta(days=10) # 10 calendar days ensures 5 trading days

        candles_df = fetch_upstox_intraday_candles(
            clean_symbol, fetch_start, fetch_end, upstox_token, "15minute"
        )
        
        if candles_df.empty: continue
        candles_df = candles_df[candles_df['timestamp'] >= entry_time].reset_index(drop=True)
        if candles_df.empty: continue

        exit_price, exit_time, exit_reason = None, None, None
        bars_in_trade = 0
        unique_days = []

        for i, candle in candles_df.iterrows():
            bars_in_trade += 1
            c_time, open_p, high_p, low_p = candle['timestamp'], candle['open'], candle['high'], candle['low']
            c_date = c_time.date()

            # Track unique trading days
            if c_date not in unique_days:
                unique_days.append(c_date)
                
                # Check for Market Open Gaps (Day 2 onwards)
                if len(unique_days) > 1:
                    if strategy_type == "long":
                        if open_p >= target_price:
                            exit_price, exit_time, exit_reason = open_p, c_time, "Target Hit (Gap-Up)"
                            break
                        elif open_p <= sl_price:
                            exit_price, exit_time, exit_reason = open_p, c_time, "SL Hit (Gap-Down)"
                            break
                    else:
                        if open_p <= target_price:
                            exit_price, exit_time, exit_reason = open_p, c_time, "Target Hit (Gap-Down)"
                            break
                        elif open_p >= sl_price:
                            exit_price, exit_time, exit_reason = open_p, c_time, "SL Hit (Gap-Up)"
                            break

            # 5-Day Hard Exit at the market Open of the 6th day
            if len(unique_days) > max_hold_days:
                exit_price, exit_time, exit_reason = open_p, c_time, f"Time Exit ({max_hold_days} Days)"
                break

            # Intraday Check
            if strategy_type == "long":
                if high_p >= target_price:
                    exit_price, exit_time, exit_reason = target_price, c_time, "Target Hit"
                    break
                elif low_p <= sl_price:
                    exit_price, exit_time, exit_reason = sl_price, c_time, "SL Hit"
                    break
            else:
                if low_p <= target_price:
                    exit_price, exit_time, exit_reason = target_price, c_time, "Target Hit"
                    break
                elif high_p >= sl_price:
                    exit_price, exit_time, exit_reason = sl_price, c_time, "SL Hit"
                    break

        if exit_price is None:
            last = candles_df.iloc[-1]
            exit_price, exit_time, exit_reason = last['close'], last['timestamp'], "Data Ended"

        pnl_abs = (exit_price - entry_price) if strategy_type == "long" else (entry_price - exit_price)
        
        trade_results.append({
            'symbol': clean_symbol,
            'entry_date': entry_time.strftime("%Y-%m-%d"),
            'entry_price': round(entry_price, 2),
            'exit_date': exit_time.strftime("%Y-%m-%d"),
            'exit_price': round(exit_price, 2),
            'pnl_abs': round(pnl_abs, 2),
            'pnl_pct': round((pnl_abs / entry_price) * 100, 2),
            'days_held': len(unique_days),
            'bars_in_trade': bars_in_trade,
            'exit_reason': exit_reason
        })

    return pd.DataFrame(trade_results)
