import pandas as pd

def calculate_advanced_metrics(trades_df):
    if trades_df.empty:
        return {}, pd.DataFrame()

    # Stock-Level Summary
    stock_group = trades_df.groupby('symbol')
    stock_summary = stock_group.agg(
        total_trades=('pnl_abs', 'count'),
        total_pnl_abs=('pnl_abs', 'sum'),
        win_rate=('pnl_abs', lambda x: round((x > 0).mean() * 100, 2))
    ).reset_index()

    # Strategy Level Metrics
    total_trades = len(trades_df)
    winning_trades = (trades_df['pnl_abs'] > 0).sum()
    overall_win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades > 0 else 0
    total_pnl = round(trades_df['pnl_abs'].sum(), 2)

    # Max Drawdown
    trades_df['cum_pnl'] = trades_df['pnl_abs'].cumsum()
    trades_df['peak'] = trades_df['cum_pnl'].cummax()
    trades_df['drawdown'] = trades_df['cum_pnl'] - trades_df['peak']
    max_drawdown = round(trades_df['drawdown'].min(), 2)

    overall_metrics = {
        "Total Trades": total_trades,
        "Win Rate (%)": overall_win_rate,
        "Total PnL (₹)": total_pnl,
        "Max Drawdown (₹)": max_drawdown
    }
    return overall_metrics, stock_summary
