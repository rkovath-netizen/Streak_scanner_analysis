import pandas as pd
import numpy as np

def calculate_advanced_metrics(trades_df):
    """
    Computes stock-level summaries, overall portfolio metrics, 2-sigma standard deviations,
    and maximum drawdowns dynamically for both Options and Cash trades.
    """
    if trades_df.empty:
        return {}, pd.DataFrame()

    # 1. Dynamic Column Detection
    # Identifies if this is an Options trade table ('cash_symbol') or Cash trade table ('symbol')
    sym_col = 'cash_symbol' if 'cash_symbol' in trades_df.columns else ('symbol' if 'symbol' in trades_df.columns else trades_df.columns[0])
    entry_price_col = 'opt_entry_price' if 'opt_entry_price' in trades_df.columns else 'entry_price'
    
    # Handle backward compatibility if bars_in_trade is missing
    bars_col = 'bars_in_trade' if 'bars_in_trade' in trades_df.columns else 'days_held'

    # 2. Stock-Level Summary
    stock_group = trades_df.groupby(sym_col)
    
    stock_summary = stock_group.agg(
        total_trades=('pnl_abs', 'count'),
        total_pnl_abs=('pnl_abs', 'sum'),
        avg_pnl_pct=('pnl_pct', 'mean'),
        win_rate=('pnl_abs', lambda x: round((x > 0).mean() * 100, 2)),
        avg_bars=(bars_col, 'mean'),
        std_bars=(bars_col, 'std')
    ).reset_index()

    # Standardize column name for the final report
    stock_summary.rename(columns={sym_col: 'symbol'}, inplace=True)

    # Calculate 2-sigma bar range per stock safely
    stock_summary['avg_bars'] = stock_summary['avg_bars'].fillna(0)
    stock_summary['std_bars'] = stock_summary['std_bars'].fillna(0)
    stock_summary['bars_2sigma_low'] = (stock_summary['avg_bars'] - 2 * stock_summary['std_bars']).clip(lower=0).round(1)
    stock_summary['bars_2sigma_high'] = (stock_summary['avg_bars'] + 2 * stock_summary['std_bars']).round(1)
    stock_summary['bars_2sigma_range'] = stock_summary['bars_2sigma_low'].astype(str) + " - " + stock_summary['bars_2sigma_high'].astype(str)

    # 3. Overall Strategy Level Metrics
    total_trades = len(trades_df)
    winning_trades = (trades_df['pnl_abs'] > 0).sum()
    overall_win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0
    
    total_pnl = round(trades_df['pnl_abs'].sum(), 2)
    overall_pnl_pct = round(trades_df['pnl_pct'].sum(), 2)

    # Global Bars in trade stats
    mean_bars = trades_df[bars_col].mean()
    std_bars = trades_df[bars_col].std() if total_trades > 1 else 0
    if pd.isna(std_bars): std_bars = 0
    
    bars_2sigma_upper = round(mean_bars + (2 * std_bars), 2)
    bars_2sigma_lower = round(max(0, mean_bars - (2 * std_bars)), 2)

    # 4. Calculate Max Drawdown
    trades_df_copy = trades_df.copy()
    trades_df_copy['cum_pnl'] = trades_df_copy['pnl_abs'].cumsum()
    trades_df_copy['peak'] = trades_df_copy['cum_pnl'].cummax()
    trades_df_copy['drawdown'] = trades_df_copy['cum_pnl'] - trades_df_copy['peak']
    max_drawdown_abs = round(trades_df_copy['drawdown'].min(), 2) if not trades_df_copy['drawdown'].empty else 0
    
    # 5. Capital Used Per Day Analysis
    if 'entry_date' in trades_df_copy.columns and entry_price_col in trades_df_copy.columns:
        # Group by pure Date (ignore time)
        trades_df_copy['entry_date_dt'] = pd.to_datetime(trades_df_copy['entry_date']).dt.date
        daily_capital = trades_df_copy.groupby('entry_date_dt')[entry_price_col].sum()
        
        mean_daily_capital = daily_capital.mean() if not daily_capital.empty else 0
        std_daily_capital = daily_capital.std() if len(daily_capital) > 1 else 0
        if pd.isna(std_daily_capital): std_daily_capital = 0
        
        capital_2sigma_upper = round(mean_daily_capital + (2 * std_daily_capital), 2)
        capital_2sigma_lower = round(max(0, mean_daily_capital - (2 * std_daily_capital)), 2)
    else:
        mean_daily_capital, capital_2sigma_lower, capital_2sigma_upper = 0, 0, 0

    # Package Final Dictionary
    overall_metrics = {
        "Total Trades": total_trades,
        "Win Rate (%)": overall_win_rate,
        "Total PnL (Abs)": total_pnl,
        "Cumulative PnL (%)": overall_pnl_pct,
        "Avg Bars in Trade": round(mean_bars, 2) if not pd.isna(mean_bars) else 0,
        "Bars 2-Sigma Range": f"[{bars_2sigma_lower}, {bars_2sigma_upper}]",
        "Max Drawdown (Abs)": max_drawdown_abs,
        "Avg Daily Capital Used": round(mean_daily_capital, 2) if not pd.isna(mean_daily_capital) else 0,
        "Daily Capital 2-Sigma Range": f"[{capital_2sigma_lower}, {capital_2sigma_upper}]"
    }

    return overall_metrics, stock_summary
