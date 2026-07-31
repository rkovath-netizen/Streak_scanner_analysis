import pandas as pd
from datetime import timedelta
import traceback
from upstox_data import get_atm_option_instrument, fetch_upstox_intraday_candles

def process_streak_options_batch(csv_files, upstox_token, strategy_type, tp_pct, sl_pct, max_hold_days, progress_callback):
    all_signals = []
    
    for f in csv_files:
        try:
            df = pd.read_csv(f)
            # --- DEBUG: Sanitize Column Names ---
            # Lowercases all columns and removes hidden spaces
            df.columns = df.columns.str.strip().str.lower()
            all_signals.append(df)
        except Exception as e:
            print(f"[ERROR] Failed to read CSV {f.name}: {e}")

    if not all_signals: 
        print("[DEBUG] No valid CSV data found.")
        return pd.DataFrame()

    combined_df = pd.concat(all_signals, ignore_index=True)
    
    # --- DEBUG: Ensure columns exist ---
    req_cols = ['seg_sym', 'time', 'ltp']
    for col in req_cols:
        if col not in combined_df.columns:
            raise ValueError(f"CRITICAL: Missing column '{col}' in CSV. Found: {list(combined_df.columns)}")

    # Convert time safely
    combined_df['time'] = pd.to_datetime(combined_df['time'], errors='coerce')
    combined_df = combined_df.dropna(subset=['time']) # Drop rows where time formatting failed

    trade_results = []
    total_trades = len(combined_df)

    for idx, row in combined_df.iterrows():
        try:
            cash_symbol = str(row['seg_sym']).strip()
            signal_time = row['time']
            cash_ltp = float(row['ltp'])
            opt_type = "CE" if strategy_type == "long" else "PE"

            if progress_callback:
                progress_callback(idx + 1, total_trades, f"Processing {cash_symbol} Options")

            # 1. ATM Mapping
            inst_key, opt_symbol = get_atm_option_instrument(cash_symbol, signal_time, cash_ltp, opt_type)
            if not inst_key: 
                print(f"[DEBUG] Could not map ATM option for {cash_symbol} at {cash_ltp}")
                continue

            # 2. Data Fetch
            fetch_start = signal_time
            fetch_end = signal_time + timedelta(days=10)
            
            opt_candles = fetch_upstox_intraday_candles(inst_key, fetch_start, fetch_end, upstox_token, "15minute")
            if opt_candles.empty: 
                print(f"[DEBUG] Upstox returned empty data for {opt_symbol} ({inst_key})")
                continue

            opt_candles = opt_candles[opt_candles['timestamp'] >= signal_time].reset_index(drop=True)
            if opt_candles.empty: 
                print(f"[DEBUG] No candle data found strictly AFTER {signal_time} for {opt_symbol}")
                continue

            # 3. Anchor Options Entry Price
            opt_entry_price = opt_candles.iloc[0]['close'] 
            target_price = opt_entry_price * (1 + tp_pct)
            sl_price = opt_entry_price * (1 - sl_pct)

            exit_price, exit_time, exit_reason = None, None, None
            bars_in_trade, unique_days = 0, []

            # 4. Step-Through Options Execution
            for i, candle in opt_candles.iterrows():
                bars_in_trade += 1
                c_time = candle['timestamp']
                open_p, high_p, low_p = candle['open'], candle['high'], candle['low']
                c_date = c_time.date()

                if c_date not in unique_days:
                    unique_days.append(c_date)
                    if len(unique_days) > 1:
                        if open_p >= target_price:
                            exit_price, exit_time, exit_reason = open_p, c_time, "Target Hit (Gap-Up)"
                            break
                        elif open_p <= sl_price:
                            exit_price, exit_time, exit_reason = open_p, c_time, "SL Hit (Gap-Down)"
                            break

                if len(unique_days) > max_hold_days:
                    exit_price, exit_time, exit_reason = open_p, c_time, f"Time Exit ({max_hold_days} Days)"
                    break

                if high_p >= target_price:
                    exit_price, exit_time, exit_reason = target_price, c_time, "Target Hit"
                    break
                elif low_p <= sl_price:
                    exit_price, exit_time, exit_reason = sl_price, c_time, "SL Hit"
                    break

            if exit_price is None:
                last = opt_candles.iloc[-1]
                exit_price, exit_time, exit_reason = last['close'], last['timestamp'], "Data Ended"

            pnl_abs = exit_price - opt_entry_price
            
            trade_results.append({
                'cash_symbol': cash_symbol,
                'cash_signal_price': round(cash_ltp, 2),
                'options_contract': opt_symbol,
                'entry_date': signal_time.strftime("%Y-%m-%d %H:%M:%S"),
                'opt_entry_price': round(opt_entry_price, 2),
                'exit_date': exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                'opt_exit_price': round(exit_price, 2),
                'pnl_abs': round(pnl_abs, 2),
                'pnl_pct': round((pnl_abs / opt_entry_price) * 100, 2),
                'days_held': len(unique_days),
                'bars_in_trade': bars_in_trade,
                'exit_reason': exit_reason
            })
            
        except Exception as e:
            print(f"[ERROR] Failed processing row {idx} for symbol {row.get('seg_sym', 'Unknown')}: {e}")
            traceback.print_exc()

    return pd.DataFrame(trade_results)
