import pandas as pd
from datetime import timedelta
from upstox_data import get_atm_option_instrument, fetch_upstox_intraday_candles

def process_streak_options_batch(csv_files, upstox_token, strategy_type, tp_pct, sl_pct, max_hold_days, progress_callback, ui_log):
    all_signals = []
    for f in csv_files:
        df = pd.read_csv(f)
        df.columns = df.columns.str.strip().str.lower()
        all_signals.append(df)

    if not all_signals: 
        return pd.DataFrame(), pd.DataFrame()
        
    combined_df = pd.concat(all_signals, ignore_index=True)
    combined_df['time'] = pd.to_datetime(combined_df['time'], errors='coerce')
    combined_df = combined_df.dropna(subset=['time']) 

    trade_results = []
    audit_logs = []
    total_trades = len(combined_df)

    for idx, row in combined_df.iterrows():
        cash_symbol = str(row['seg_sym']).replace("NSE:", "").replace("BSE:", "").strip()
        signal_time = row['time']
        cash_ltp = float(row.get('ltp', 0.0))
        opt_type = "CE" if strategy_type == "long" else "PE"

        if progress_callback: 
            progress_callback(idx + 1, total_trades, f"Processing {cash_symbol}")

        # 1. ATM Mapping
        inst_key, opt_symbol, map_status = get_atm_option_instrument(cash_symbol, signal_time, cash_ltp, opt_type, ui_log)
        
        if not inst_key:
            audit_logs.append({
                'cash_symbol': cash_symbol,
                'signal_time': signal_time,
                'cash_ltp': cash_ltp,
                'status': 'FAILED',
                'reason': map_status,
                'options_contract': 'N/A'
            })
            continue

        # 2. Data Fetch
        fetch_start = signal_time
        fetch_end = signal_time + timedelta(days=10)
        opt_candles = fetch_upstox_intraday_candles(inst_key, fetch_start, fetch_end, upstox_token, ui_log)
        
        if opt_candles.empty:
            audit_logs.append({
                'cash_symbol': cash_symbol,
                'signal_time': signal_time,
                'cash_ltp': cash_ltp,
                'status': 'FAILED',
                'reason': '0 Candles Returned (Illiquid / Expired)',
                'options_contract': opt_symbol
            })
            continue

        opt_candles = opt_candles[opt_candles['timestamp'] >= signal_time].reset_index(drop=True)
        if opt_candles.empty:
            audit_logs.append({
                'cash_symbol': cash_symbol,
                'signal_time': signal_time,
                'cash_ltp': cash_ltp,
                'status': 'FAILED',
                'reason': 'No Candles Strictly After Signal Time',
                'options_contract': opt_symbol
            })
            continue

        # 3. Simulate Trade
        opt_entry_price = opt_candles.iloc[0]['close'] 
        target_price = opt_entry_price * (1 + tp_pct)
        sl_price = opt_entry_price * (1 - sl_pct)

        exit_price, exit_time, exit_reason = None, None, None
        bars_in_trade, unique_days = 0, []

        for i, candle in opt_candles.iterrows():
            bars_in_trade += 1
            c_time, open_p, high_p, low_p = candle['timestamp'], candle['open'], candle['high'], candle['low']
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

        audit_logs.append({
            'cash_symbol': cash_symbol,
            'signal_time': signal_time,
            'cash_ltp': cash_ltp,
            'status': 'SUCCESS',
            'reason': 'Trade Executed',
            'options_contract': opt_symbol
        })

    return pd.DataFrame(trade_results), pd.DataFrame(audit_logs)
