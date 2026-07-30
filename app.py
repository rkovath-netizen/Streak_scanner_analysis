import streamlit as st
import pandas as pd
from datetime import datetime
from strategy_engine import process_streak_batch
from metrics_calculator import calculate_advanced_metrics
from github_utils import push_csv_to_github

# --- 1. Page Config & Secrets Initialization ---
st.set_page_config(page_title="Streak Scanner Backtest Engine", layout="wide")
st.title("📈 Streak Swing Backtest Engine (5-Day Hold)")

# Explicitly fetch all required tokens from Streamlit Secrets
try:
    UPSTOX_TOKEN = st.secrets["UPSTOX_ACCESS_TOKEN"]
    GITHUB_PAT = st.secrets["GITHUB_PAT"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
except KeyError as e:
    st.error(f"⚠️ Missing secret: {e}. Please add it to your Streamlit secrets.")
    st.stop()

# --- 2. Sidebar Configuration ---
st.sidebar.header("⚙️ Configuration Settings")
strategy_name = st.sidebar.text_input("Strategy Name", value="15_MT_Momentum")
strategy_type = st.sidebar.selectbox("Setup Direction", ["long", "short"])
tp_pct = st.sidebar.number_input("Target Profit (%)", min_value=0.5, value=5.0) / 100.0
sl_pct = st.sidebar.number_input("Stop Loss (%)", min_value=0.5, value=3.0) / 100.0
max_hold_days = st.sidebar.number_input("Max Holding Days", min_value=1, value=5)

# --- 3. File Upload Section ---
uploaded_files = st.file_uploader(
    "Upload Zerodha Streak CSV Exports", 
    type=["csv"], 
    accept_multiple_files=True
)

if uploaded_files and st.button("🚀 Run Backtest"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(current, total, message):
        pct = int((current / total) * 100)
        progress_bar.progress(pct)
        status_text.text(f"[{current}/{total}] {message}")

    with st.spinner("Simulating trades via Upstox intraday data..."):
        trades_df = process_streak_batch(
            csv_files=uploaded_files,
            upstox_token=UPSTOX_TOKEN,
            strategy_type=strategy_type,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            max_hold_days=max_hold_days,
            progress_callback=update_progress
        )

    if trades_df.empty:
        st.error("No trades executed or market data missing.")
    else:
        st.success("✅ Backtest Execution Complete!")

        # --- 4. Render Metrics ---
        overall_metrics, stock_summary = calculate_advanced_metrics(trades_df)
        
        st.subheader("📊 Portfolio Performance Summary")
        m_cols = st.columns(4)
        m_cols[0].metric("Total Trades", overall_metrics["Total Trades"])
        m_cols[1].metric("Win Rate", f"{overall_metrics['Win Rate (%)']}%")
        m_cols[2].metric("Total PnL (Abs)", f"₹{overall_metrics['Total PnL (Abs)']}")
        m_cols[3].metric("Max Drawdown", f"₹{overall_metrics['Max Drawdown (Abs)']}")

        st.subheader("📌 Stock Level Summary")
        st.dataframe(stock_summary, use_container_width=True)

        st.subheader("📄 Detailed Trade Log")
        st.dataframe(trades_df, use_container_width=True)

        # --- 5. Export to GitHub ---
        csv_buffer = trades_df.to_csv(index=False)
        st.markdown("---")
        
        if st.button("🐙 Save Output to GitHub"):
            with st.spinner("Pushing file to GitHub repository..."):
                success, response_msg = push_csv_to_github(
                    csv_content=csv_buffer,
                    strategy_name=strategy_name,
                    pat_token=GITHUB_PAT,
                    repo_name=GITHUB_REPO,
                    branch=GITHUB_BRANCH
                )
                if success:
                    st.success(f"✅ Successfully saved to GitHub: `{response_msg}`")
                else:
                    st.error(f"❌ GitHub Commit failed: {response_msg}")
