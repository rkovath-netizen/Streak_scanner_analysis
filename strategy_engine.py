import pandas as pd
from datetime import timedelta
from upstox_data import fetch_upstox_intraday_candles, get_nfo_lot_size, get_option_legs

def get_premium_at_time(df, target_time, use_open=False):
    past = df[df['timestamp'] <= target_time]
    if not past.empty: return past.iloc[-1]['open'] if use_open else past.iloc[-1]['close']
    future = df[df['timestamp'] >= target_time]
    if not future.empty: return future.iloc[0]['open']
    return 0.0

def process_streak_comparative_batch(csv_files, upstox_token, setup_direction, tp_pct, sl_pct, max_hold_days, progress_callback=None, log_func=print):
    all_signals = []
    
    for f in csv_files:
        try:
            log_func(f"📄 Reading file: {f.name} (Size: {f.size} bytes)")
            df = pd.read_csv(f)
            if not df.empty and 'seg_sym' in df.columns and 'time' in df.columns:
                all_signals.append(df)
                log_func(f"✅ Loaded {len(df)} signal rows from {f.name}")
            else:
                log_func(f"⚠️ Skipped {f.name}: Missing 'seg_sym' or 'time' columns.")
        except Exception as e:
            log_func(f"❌ Error parsing {f.name}: {e}")

    if not all_signals:
        log_func("❌ No valid signals found across uploaded CSV files.")
        return pd.DataFrame()

    combined_df = pd.concat(all_signals, ignore_index=True)
    combined_df['time'] = pd.to_datetime(combined_df['time'])
    trade_results = []
    total_trades = len(combined_df)
    
    api_cache = {}
    is_bullish = (setup_direction == "Bullish")
    
    strategies = [
        "Long Equity", "Short Equity", 
        "Options: Naked Call Buy", "Options: Naked Put Buy", "Options: Long Straddle", 
        "Options: Bull Put Spread (ATM & OTM1)", "Options: Bull Put Spread (ATM & OTM2)",
        "Options: Bear Call Spread (ATM & OTM1)", "Options: Bear Call Spread (ATM & OTM2)"
    ]

    log_func(f"🚀 Starting backtest processing for {total_trades} trade signals...")

    for idx, row in combined_df.iterrows():
        raw_symbol = row['seg_sym']
        entry_time = row['time']
        entry_price = float(row['ltp'])
        clean_symbol = raw_symbol.replace("NSE:", "").replace("BSE:", "").strip()
        lot_size = get_nfo_lot_size(clean_symbol)

        if progress_callback:
            progress_callback(idx + 1, total_trades, f"Processing Trade {idx+1}/{total_trades}: {clean_symbol}")

        log_func(f"🔍 Trade {idx+1}: {clean_symbol} | Entry: {entry_price} | Lot: {lot_size}")

        target_price = entry_price * (1 + tp_pct) if is_bullish else entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 - sl_pct) if is_bullish else entry_price * (1 + sl_pct)

        fetch_start = entry_time
        fetch_end = entry_time + timedelta(days=10) 

        spot_df = fetch_upstox_intraday_candles(clean_symbol, fetch_start, fetch_end, upstox_token, is_key=False, log_func=log_func)
        if spot_df.empty:
            log_func(f"⚠️ Could not retrieve candles for {clean_symbol}. Skipping.")
            continue
            
        spot_df = spot_df[spot_df['timestamp'] >= entry_time].reset_index(drop=True)
        if spot_df.empty:
            continue

        exit_time, exit_reason, is_gap_exit = None, None, False
        unique_days = []

        for i, candle in spot_df.iterrows():
            c_time, c_date = candle['timestamp'], candle['timestamp'].date()
            open_p, high_p, low_p = candle['open'], candle['high'], candle['low']

            if c_date not in unique_days:
                unique_days.append(c_date)
                if len(unique_days) > 1:
                    if is_bullish:
                        if open_p >= target_price: exit_time, exit_reason, is_gap_exit = c_time, "Target Hit on Gap-Up", True; break
                        elif open_p <= sl_price: exit_time, exit_reason, is_gap_exit = c_time, "SL Hit on Gap-Down", True; break
                    else:
                        if open_p <= target_price: exit_time, exit_reason, is_gap_exit = c_time, "Target Hit on Gap-Down", True; break
                        elif open_p >= sl_price: exit_time, exit_reason, is_gap_exit = c_time, "SL Hit on Gap-Up", True; break

            if len(unique_days) > max_hold_days:
                exit_time, exit_reason, is_gap_exit = c_time, f"Time Exit ({max_hold_days} Days)", True; break

            if is_bullish:
                if high_p >= target_price: exit_time, exit_reason, is_gap_exit = c_time, f"Target Hit (+{tp_pct*100:.1f}%)", False; break
                elif low_p <= sl_price: exit_time, exit_reason, is_gap_exit = c_time, f"SL Hit (-{sl_pct*100:.1f}%)", False; break
            else:
                if low_p <= target_price: exit_time, exit_reason, is_gap_exit = c_time, f"Target Hit (+{tp_pct*100:.1f}%)", False; break
                elif high_p >= sl_price: exit_time, exit_reason, is_gap_exit = c_time, f"SL Hit (-{sl_pct*100:.1f}%)", False; break

        if not exit_time:
            exit_time = spot_df.iloc[-1]['timestamp']
            exit_reason = "Data Ended"
            is_gap_exit = False

        log_func(f"🎯 Exit: {exit_time} | Reason: {exit_reason}")

        trade_data = {
            'Symbol': clean_symbol, 'Lot Size': lot_size,
            'Entry Time': entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            'Exit Time': exit_time.strftime("%Y-%m-%d %H:%M:%S"),
            'Days Held': len(unique_days), 'Exit Reason': exit_reason
        }

        for strat in strategies:
            pnl_abs = 0.0
            if strat in ["Long Equity", "Short Equity"]:
                underlying_exit = spot_df[spot_df['timestamp'] == exit_time].iloc[0]
                exit_price = underlying_exit['open'] if is_gap_exit else underlying_exit['close']
                pnl_abs = (exit_price - entry_price) * lot_size if strat == "Long Equity" else (entry_price - exit_price) * lot_size
            else:
                legs = get_option_legs(clean_symbol, entry_time, entry_price, strat)
                for leg in legs:
                    cache_key = f"{leg['key']}_{fetch_start.date()}"
                    if cache_key not in api_cache:
                        api_cache[cache_key] = fetch_upstox_intraday_candles(leg['key'], fetch_start, fetch_end, upstox_token, is_key=True, log_func=log_func)
                    
                    leg_df = api_cache[cache_key]
                    if not leg_df.empty:
                        leg_entry = get_premium_at_time(leg_df, entry_time, use_open=False)
                        leg_exit = get_premium_at_time(leg_df, exit_time, use_open=is_gap_exit)
                        pnl_abs += (leg_exit - leg_entry) * leg['side'] * lot_size
            
            capital_exposure = entry_price * lot_size
            pnl_pct = (pnl_abs / capital_exposure) * 100 if capital_exposure > 0 else 0
            
            trade_data[f"{strat} PnL (₹)"] = round(pnl_abs, 2)
            trade_data[f"{strat} Return (%)"] = round(pnl_pct, 2)

        trade_results.append(trade_data)

    return pd.DataFrame(trade_results)
