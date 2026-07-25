import pandas as pd
import numpy as np

def calculate_advanced_metrics(trades_df):
    """
    Computes stock-level summaries, overall portfolio metrics, 2-sigma standard deviations,
    and maximum drawdowns.
    """
    if trades_df.empty:
        return {}, pd.DataFrame()

    # 1. Stock-Level Summary
    stock_group = trades_df.groupby('symbol')
    
    stock_summary = stock_group.agg(
        total_trades=('pnl_abs', 'count'),
        total_pnl_abs=('pnl_abs', 'sum'),
        avg_pnl_pct=('pnl_pct', 'mean'),
        win_rate=('pnl_abs', lambda x: round((x > 0).mean() * 100, 2)),
        avg_bars=('bars_in_trade', 'mean'),
        std_bars=('bars_in_trade', 'std')
    ).reset_index()

    # Calculate 2-sigma bar range per stock
    stock_summary['bars_2sigma_low'] = (stock_summary['avg_bars'] - 2 * stock_summary['std_bars'].fillna(0)).clip(lower=0).round(1)
    stock_summary['bars_2sigma_high'] = (stock_summary['avg_bars'] + 2 * stock_summary['std_bars'].fillna(0)).round(1)
    stock_summary['bars_2sigma_range'] = stock_summary['bars_2sigma_low'].astype(str) + " - " + stock_summary['bars_2sigma_high'].astype(str)

    # 2. Overall Strategy Level Metrics
    total_trades = len(trades_df)
    winning_trades = (trades_df['pnl_abs'] > 0).sum()
    overall_win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0
    
    total_pnl = round(trades_df['pnl_abs'].sum(), 2)
    overall_pnl_pct = round(trades_df['pnl_pct'].sum(), 2)

    # Bars in trade stats
    mean_bars = trades_df['bars_in_trade'].mean()
    std_bars = trades_df['bars_in_trade'].std() if total_trades > 1 else 0
    bars_2sigma_upper = round(mean_bars + (2 * std_bars), 2)
    bars_2sigma_lower = round(max(0, mean_bars - (2 * std_bars)), 2)

    # Calculate Max Drawdown
    trades_df['cum_pnl'] = trades_df['pnl_abs'].cumsum()
    trades_df['peak'] = trades_df['cum_pnl'].cummax()
    trades_df['drawdown'] = trades_df['cum_pnl'] - trades_df['peak']
    max_drawdown_abs = round(trades_df['drawdown'].min(), 2)
    
    # Capital Used Per Day Analysis
    trades_df['entry_date_dt'] = pd.to_datetime(trades_df['entry_date'])
    daily_capital = trades_df.groupby('entry_date_dt')['entry_price'].sum()
    
    mean_daily_capital = daily_capital.mean()
    std_daily_capital = daily_capital.std() if len(daily_capital) > 1 else 0
    
    capital_2sigma_upper = round(mean_daily_capital + (2 * std_daily_capital), 2)
    capital_2sigma_lower = round(max(0, mean_daily_capital - (2 * std_daily_capital)), 2)

    overall_metrics = {
        "Total Trades": total_trades,
        "Win Rate (%)": overall_win_rate,
        "Total PnL (Abs)": total_pnl,
        "Cumulative PnL (%)": overall_pnl_pct,
        "Avg Bars in Trade": round(mean_bars, 2),
        "Bars 2-Sigma Range": f"[{bars_2sigma_lower}, {bars_2sigma_upper}]",
        "Max Drawdown (Abs)": max_drawdown_abs,
        "Avg Daily Capital Used": round(mean_daily_capital, 2),
        "Daily Capital 2-Sigma Range": f"[{capital_2sigma_lower}, {capital_2sigma_upper}]"
    }

    return overall_metrics, stock_summary
