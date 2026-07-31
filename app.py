import streamlit as st
import pandas as pd
from datetime import datetime
from strategy_engine import process_streak_batch
from metrics_calculator import calculate_advanced_metrics
from github_utils import push_csv_to_github

st.set_page_config(page_title="Streak & Options Backtester", layout="wide")
st.title("📈 Streak Momentum & Options Spread Backtester")

# Sidebar Configuration
st.sidebar.header("⚙️ Configuration")
strategy_name = st.sidebar.text_input("Strategy Name", value="15_MT_Momentum")

# The 7 Strategies including the 5 new Options strategies
strategy_options = [
    "Long Equity", 
    "Short Equity", 
    "Options: Long Straddle", 
    "Options: Bull Put Spread (ATM & OTM1)",
    "Options: Bull Put Spread (ATM & OTM2)",
    "Options: Bear Call Spread (ATM & OTM1)",
    "Options: Bear Call Spread (ATM & OTM2)"
]
selected_strategy = st.sidebar.selectbox("Select Strategy", strategy_options)

tp_pct = st.sidebar.number_input("Underlying Target Profit (%)", min_value=0.5, value=5.0, step=0.5) / 100.0
sl_pct = st.sidebar.number_input("Underlying Stop Loss (%)", min_value=0.5, value=3.0, step=0.5) / 100.0
max_hold_days = st.sidebar.number_input("Max Holding Days", min_value=1, value=5, step=1)

# Retrieve Secrets safely
try:
    upstox_token = st.secrets["UPSTOX_ACCESS_TOKEN"]
    github_pat = st.secrets["GITHUB_PAT"]
    github_repo = st.secrets["GITHUB_REPO"]
    github_branch = st.secrets.get("GITHUB_BRANCH", "main")
    secrets_loaded = True
except KeyError as e:
    secrets_loaded = False
    st.sidebar.error(f"⚠️ Missing Secret: {e}")

# File Upload
uploaded_files = st.file_uploader("Upload Streak CSV Scanner Exports", type=["csv"], accept_multiple_files=True)

if uploaded_files and secrets_loaded and st.button("🚀 Run Options Backtest"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(current, total, message):
        progress_bar.progress(int((current / total) * 100))
        status_text.text(f"[{current}/{total}] {message}")

    with st.spinner("Simulating trades and fetching Option Chains..."):
        trades_df = process_streak_batch(
            csv_files=uploaded_files, upstox_token=upstox_token,
            strategy_type=selected_strategy, tp_pct=tp_pct, sl_pct=sl_pct,
            max_hold_days=max_hold_days, progress_callback=update_progress
        )

    if trades_df.empty:
        st.error("No trades executed or market data missing.")
    else:
        st.success("✅ Backtest Complete!")
        overall_metrics, stock_summary = calculate_advanced_metrics(trades_df)

        m_cols = st.columns(4)
        m_cols[0].metric("Total Trades", overall_metrics["Total Trades"])
        m_cols[1].metric("Win Rate", f"{overall_metrics['Win Rate (%)']}%")
        m_cols[2].metric("Total PnL", f"₹{overall_metrics['Total PnL (₹)']}")
        m_cols[3].metric("Max Drawdown", f"₹{overall_metrics['Max Drawdown (₹)']}")

        st.subheader("📄 Trade Log (Prices Adjusted for Lot Size)")
        st.dataframe(trades_df, use_container_width=True)

        # Export Logic
        csv_buffer = trades_df.to_csv(index=False)
        st.markdown("---")
        col1, col2 = st.columns(2)
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"{strategy_name.lower()}_{timestamp_str}.csv"

        with col1:
            st.download_button("📥 Download Locally", csv_buffer, export_filename, "text/csv")
        with col2:
            with st.spinner("Archiving to GitHub output folder..."):
                success, path = push_csv_to_github(csv_buffer, strategy_name, github_pat, github_repo, github_branch)
                if success:
                    st.success(f"✅ Committed to `{path}`!")
                else:
                    st.error("❌ GitHub Commit failed.")
