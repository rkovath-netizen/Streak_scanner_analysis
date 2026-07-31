import streamlit as st
import pandas as pd
import traceback
from strategy_engine import process_streak_options_batch
from github_utils import push_csv_to_github
from metrics_calculator import calculate_advanced_metrics

st.set_page_config(page_title="Streak Options Backtester", layout="wide")
st.title("📈 Streak ATM Options Backtest Engine")

# --- Debugging Area: Secrets Checking ---
try:
    UPSTOX_TOKEN = st.secrets["UPSTOX_ACCESS_TOKEN"]
    GITHUB_PAT = st.secrets["GITHUB_PAT"]
    GITHUB_REPO = st.secrets["GITHUB_REPO"]
    GITHUB_BRANCH = st.secrets.get("GITHUB_BRANCH", "main")
except KeyError as e:
    st.error(f"⚠️ Missing secret in `.streamlit/secrets.toml`: {e}")
    st.stop()

st.sidebar.header("⚙️ Settings")
strategy_name = st.sidebar.text_input("Strategy Name", value="15_MT_Momentum")
strategy_type = st.sidebar.selectbox("Signal Type", ["long", "short"])
st.sidebar.caption("Long = Buy CE | Short = Buy PE")

tp_pct = st.sidebar.number_input("Target Profit on Premium (%)", min_value=0.5, value=5.0) / 100.0
sl_pct = st.sidebar.number_input("Stop Loss on Premium (%)", min_value=0.5, value=3.0) / 100.0
max_hold = st.sidebar.number_input("Max Holding Days", min_value=1, value=5)

uploaded_files = st.file_uploader("Upload Cash Signal CSVs", type=["csv"], accept_multiple_files=True)

if uploaded_files and st.button("🚀 Run Options Backtest"):
    progress_bar = st.progress(0)
    status_text = st.empty()
    debug_expander = st.expander("🛠️ Live Execution Logs", expanded=True)

    def progress_update(current, total, msg):
        progress_bar.progress(int((current / total) * 100))
        status_text.text(f"[{current}/{total}] {msg}")

    try:
        with st.spinner("Mapping to ATM Options & Fetching Data..."):
            trades_df = process_streak_options_batch(
                uploaded_files, UPSTOX_TOKEN, strategy_type, tp_pct, sl_pct, max_hold, progress_update
            )

        if trades_df.empty:
            st.error("⚠️ No valid options trades could be executed. Check the console/terminal for debug prints.")
        else:
            st.success("✅ Backtest Complete!")
            
            overall, stock_stats = calculate_advanced_metrics(trades_df)
            st.subheader("📊 Portfolio Stats")
            cols = st.columns(4)
            cols[0].metric("Total Trades", overall.get("Total Trades", 0))
            cols[1].metric("Win Rate", f"{overall.get('Win Rate (%)', 0)}%")
            cols[2].metric("Total PnL", f"₹{overall.get('Total PnL (Abs)', 0)}")
            cols[3].metric("Max Drawdown", f"₹{overall.get('Max Drawdown (Abs)', 0)}")

            st.subheader("📄 Options Trade Log")
            st.dataframe(trades_df, use_container_width=True)

            csv_buffer = trades_df.to_csv(index=False)
            st.markdown("---")
            if st.button("🐙 Export to GitHub (output/ folder)"):
                with st.spinner("Pushing..."):
                    ok, res = push_csv_to_github(csv_buffer, strategy_name, GITHUB_PAT, GITHUB_REPO, GITHUB_BRANCH)
                    if ok: 
                        st.success(f"✅ Saved to GitHub: `{res}`")
                    else: 
                        st.error(f"❌ Failed: {res}")

    except Exception as e:
        st.error(f"🚨 A critical error occurred during execution: {e}")
        st.code(traceback.format_exc(), language="python")
