import pandas as pd
from datetime import timedelta
from upstox_data import fetch_upstox_intraday_candles, get_nfo_lot_size, get_option_legs

def get_premium_at_time(df, target_time, use_open=False):
    past_candles = df[df['timestamp'] <= target_time]
    if not past_candles.empty:
        return past_candles.iloc[-1]['open'] if use_open else past_candles.iloc[-1]['close']
    future_candles = df[df['timestamp'] >= target_time]
    if not future_candles.empty:
        return future_candles.iloc[0]['open']
    return 0.0

def process_streak_batch(csv_files, upstox_token, strategy_type, tp_pct, sl_pct, max_hold_days, progress_callback=None):
    all_signals = []
    for file in csv_files:
        all_signals.append(pd.read_csv(file))
        
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
        lot_size = get_nfo_lot_size(clean_symbol)

        if progress_callback:
            progress_callback(idx + 1, total_trades, f"Processing {clean_symbol} at {entry_time}")

        is_bullish = strategy_type in [
            "Long Equity", "Options: Long Straddle", "Options: Naked Call Buy",
            "Options: Bull Put Spread (ATM & OTM1)", "Options: Bull Put Spread (ATM & OTM2)"
        ]
        
        target_price = entry_price * (1 + tp_pct) if is_bullish else entry_price * (1 - tp_pct)
        sl_price = entry_price * (1 - sl_pct) if is_bullish else entry_price * (1 + sl_pct)

        fetch_start = entry_time
        fetch_end = entry_time + timedelta(days=10) 

        candles_df = fetch_upstox_intraday_candles(
            symbol_or_key=clean_symbol, start_dt=fetch_start, end_dt=fetch_end, 
            access_token=upstox_token, interval="15minute", is_key=False
        )

        if candles_df.empty:
            continue

        candles_df = candles_df[candles_df['timestamp'] >= entry_time].reset_index(drop=True)
        if candles_df.empty:
            continue

        exit_time, exit_reason, is_gap_exit = None, None, False
        unique_days = []

        for i, candle in candles_df.iterrows():
            c_time, c_date = candle['timestamp'], candle['timestamp'].date()
            open_p, high_p, low_p = candle['open'], candle['high'], candle['low']

            if c_date not in unique_days:
                unique_days.append(c_date)
                if len(unique_days) > 1:
                    if is_bullish:
                        if open_p >= target_price:
                            exit_time, exit_reason, is_gap_exit = c_time, "Target Hit on Gap-Up", True; break
                        elif open_p <= sl_price:
                            exit_time, exit_reason, is_gap_exit = c_time, "SL Hit on Gap-Down", True; break
                    else:
                        if open_p <= target_price:
                            exit_time, exit_reason, is_gap_exit = c_time, "Target Hit on Gap-Down", True; break
                        elif open_p >= sl_price:
                            exit_time, exit_reason, is_gap_exit = c_time, "SL Hit on Gap-Up", True; break

            if len(unique_days) > max_hold_days:
                exit_time, exit_reason, is_gap_exit = c_time, f"Time Exit ({max_hold_days} Days)", True; break

            if is_bullish:
                if high_p >= target_price:
                    exit_time, exit_reason, is_gap_exit = c_time, f"Target Hit (+{tp_pct*100:.1f}%)", False; break
                elif low_p <= sl_price:
                    exit_time, exit_reason, is_gap_exit = c_time, f"SL Hit (-{sl_pct*100:.1f}%)", False; break
            else:
                if low_p <= target_price:
                    exit_time, exit_reason, is_gap_exit = c_time, f"Target Hit (+{tp_pct*100:.1f}%)", False; break
                elif high_p >= sl_price:
                    exit_time, exit_reason, is_gap_exit = c_time, f"SL Hit (-{sl_pct*100:.1f}%)", False; break

        if not exit_time:
            exit_time = candles_df.iloc[-1]['timestamp']
            exit_reason = "Data Ended"
            is_gap_exit = False

        pnl_abs = 0.0
        details = ""

        if strategy_type in ["Long Equity", "Short Equity"]:
            underlying_exit = candles_df[candles_df['timestamp'] == exit_time].iloc[0]
            exit_price = underlying_exit['open'] if is_gap_exit else underlying_exit['close']
            
            if strategy_type == "Long Equity":
                pnl_abs = (exit_price - entry_price) * lot_size
            else:
                pnl_abs = (entry_price - exit_price) * lot_size
                
            details = f"Entry: {entry_price}, Exit: {exit_price}"
            pnl_pct = (pnl_abs / (entry_price * lot_size)) * 100

        else:
            legs = get_option_legs(clean_symbol, entry_time, entry_price, strategy_type)
            if not legs:
                continue 
                
            total_premium_involved = 0.0
            
            for leg in legs:
                leg_df = fetch_upstox_intraday_candles(
                    leg['key'], entry_time, exit_time + timedelta(days=1), 
                    upstox_token, is_key=True
                )
                if leg_df.empty: continue
                
                leg_entry = get_premium_at_time(leg_df, entry_time, use_open=False)
                leg_exit = get_premium_at_time(leg_df, exit_time, use_open=is_gap_exit)
                
                leg_pnl = (leg_exit - leg_entry) * leg['side'] * lot_size
                pnl_abs += leg_pnl
                
                action = "Buy" if leg['side'] == 1 else "Sell"
                details += f"[{leg['type']}: {action} @ {leg_entry:.2f}, Exit @ {leg_exit:.2f}] "
                total_premium_involved += leg_entry * lot_size

            pnl_pct = (pnl_abs / total_premium_involved) * 100 if total_premium_involved > 0 else 0

        trade_results.append({
            'symbol': clean_symbol,
            'lot_size': lot_size,
            'entry_time': entry_time.strftime("%Y-%m-%d %H:%M:%S"),
            'exit_time': exit_time.strftime("%Y-%m-%d %H:%M:%S"),
            'pnl_abs': round(pnl_abs, 2),
            'pnl_pct': round(pnl_pct, 2),
            'days_held': len(unique_days),
            'exit_reason': exit_reason,
            'trade_details': details
        })

    return pd.DataFrame(trade_results)
