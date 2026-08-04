import pandas as pd
import numpy as np

def calculate_advanced_metrics(trades_df):
    """
    Computes comprehensive stock-level and portfolio-level statistics, 
    including 2-sigma ranges for holding periods and daily capital utilization.
    """
    if trades_df.empty:
        return {}, pd.DataFrame()

    # -----------------------------------------
    # 1. STOCK LEVEL SUMMARY
    # -----------------------------------------
    stock_group = trades_df.groupby('symbol')
    
    stock_summary = stock_group.agg(
        total_trades=('pnl_abs', 'count'),
        total_pnl_abs=('pnl_abs', 'sum'),
        avg_pnl_pct=('pnl_pct', 'mean'),
        win_rate=('pnl_abs', lambda x: round((x > 0).mean() * 100, 2)),
        avg_days_held=('days_held', 'mean'),
        std_days_held=('days_held', 'std')
    ).reset_index()

    # 2-Sigma Range for holding period at stock level
    stock_summary['days_2sigma_low'] = (stock_summary['avg_days_held'] - 2 * stock_summary['std_days_held'].fillna(0)).clip(lower=0).round(1)
    stock_summary['days_2sigma_high'] = (stock_summary['avg_days_held'] + 2 * stock_summary['std_days_held'].fillna(0)).round(1)
    stock_summary['days_2sigma_range'] = stock_summary['days_2sigma_low'].astype(str) + " to " + stock_summary['days_2sigma_high'].astype(str)

    # -----------------------------------------
    # 2. OVERALL PORTFOLIO METRICS
    # -----------------------------------------
    total_trades = len(trades_df)
    winning_trades = (trades_df['pnl_abs'] > 0).sum()
    overall_win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0
    total_pnl = round(trades_df['pnl_abs'].sum(), 2)
    overall_pnl_pct = round(trades_df['pnl_pct'].mean(), 2) # Average return per trade

    # Days in Trade 2-Sigma Stats
    mean_days = trades_df['days_held'].mean()
    std_days = trades_df['days_held'].std() if total_trades > 1 else 0
    days_2sigma_upper = round(mean_days + (2 * std_days), 2)
    days_2sigma_lower = round(max(0, mean_days - (2 * std_days)), 2)

    # Maximum Drawdown Calculation (Absolute ₹)
    trades_df['cum_pnl'] = trades_df['pnl_abs'].cumsum()
    trades_df['peak_pnl'] = trades_df['cum_pnl'].cummax()
    trades_df['drawdown'] = trades_df['cum_pnl'] - trades_df['peak_pnl']
    max_drawdown_abs = round(trades_df['drawdown'].min(), 2)

    # -----------------------------------------
    # 3. DAILY CAPITAL UTILIZATION & 2-SIGMA
    # -----------------------------------------
    # Assuming capital required = Entry Price * Lot Size (For Equity. Options margin differs but this acts as proxy).
    trades_df['entry_date_only'] = pd.to_datetime(trades_df['entry_time']).dt.date
    if 'lot_size' in trades_df.columns:
        # We need original underlying entry price for capital proxy, but let's approximate via total exposure
        trades_df['capital_exposure'] = trades_df.apply(lambda row: abs(row['pnl_abs'] / (row['pnl_pct']/100)) if row['pnl_pct'] != 0 else 0, axis=1)
    else:
        trades_df['capital_exposure'] = 0

    daily_capital = trades_df.groupby('entry_date_only')['capital_exposure'].sum()
    
    mean_daily_capital = daily_capital.mean()
    std_daily_capital = daily_capital.std() if len(daily_capital) > 1 else 0
    
    capital_2sigma_upper = round(mean_daily_capital + (2 * std_daily_capital), 2)
    capital_2sigma_lower = round(max(0, mean_daily_capital - (2 * std_daily_capital)), 2)

    # Build final dictionary
    overall_metrics = {
        "Total Trades": total_trades,
        "Win Rate (%)": overall_win_rate,
        "Total PnL (₹)": total_pnl,
        "Avg Trade Return (%)": overall_pnl_pct,
        "Avg Days Held": round(mean_days, 1),
        "Holding 2-Sigma Range": f"[{days_2sigma_lower}, {days_2sigma_upper}] days",
        "Max Drawdown (₹)": max_drawdown_abs,
        "Avg Daily Capital Used (₹)": round(mean_daily_capital, 2),
        "Capital 2-Sigma Range": f"[₹{capital_2sigma_lower}, ₹{capital_2sigma_upper}]"
    }

    # Clean up temp columns from trades_df before returning
    trades_df.drop(columns=['cum_pnl', 'peak_pnl', 'drawdown', 'entry_date_only', 'capital_exposure'], inplace=True, errors='ignore')

    return overall_metrics, stock_summary
