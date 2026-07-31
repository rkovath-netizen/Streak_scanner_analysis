import streamlit as st
import pandas as pd
import traceback
from strategy_engine import process_streak_options_batch
from github_utils import push_results_and_logs_to_github
from metrics_calculator import calculate_advanced_metrics

st.set_page_config(page_title="Streak Options Backtester", layout="wide")
st.title("📈 Streak ATM Options Backtest Engine")

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

tp_pct = st.sidebar.number_input("Target Profit (%)", min_value=0.5, value=5.0) / 100.0
sl_pct = st.sidebar.number_input("Stop Loss (%)", min_value=0.5, value=3.0) / 100.0
max_hold = st.sidebar.number_input("Max Holding Days", min_value=1, value=5)

uploaded_files = st.file_uploader("Upload Cash Signal CSVs", type=["csv"], accept_multiple_files=True)

if uploaded_files and st.button("🚀 Run Options Backtest"):
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    full_logs = []
    
    def ui_log(msg):
        full_logs.append(msg)

    def progress_update(current, total, msg):
        progress_bar.progress(int((current / total) * 100))
        status_text.text(f"[{current}/{total}] {msg}")

    try:
        with st.spinner("Mapping & Fetching Options..."):
            trades_df, audit_df = process_streak_options_batch(
                uploaded_files, UPSTOX_TOKEN, strategy_type, tp_pct, sl_pct, max_hold, progress_update, ui_log
            )

        st.success("✅ Execution Finished!")

        # 1. Metrics & Overview
        if not trades_df.empty:
            overall, stock_stats = calculate_advanced_metrics(trades_df)
            st.subheader("📊 Portfolio Performance Summary")
            cols = st.columns(4)
            cols[0].metric("Total Executed Trades", overall.get("Total Trades", 0))
            cols[1].metric("Win Rate", f"{overall.get('Win Rate (%)', 0)}%")
            cols[2].metric("Total PnL", f"₹{overall.get('Total PnL (Abs)', 0)}")
            cols[3].metric("Max Drawdown", f"₹{overall.get('Max Drawdown (Abs)', 0)}")

        # 2. Tabs for Results, Audit Diagnostics, and Full Raw Logs
        tab1, tab2, tab3 = st.tabs(["📄 Executed Trades", "🔍 Signal Audit Diagnostics", "📜 Live Execution Logs"])

        with tab1:
            if trades_df.empty:
                st.warning("No trades were successfully executed.")
            else:
                st.dataframe(trades_df, use_container_width=True)

        with tab2:
            st.subheader("Signal Audit (All Uploaded Signals)")
            if not audit_df.empty:
                st.dataframe(audit_df, use_container_width=True)

        with tab3:
            st.subheader("Full Raw Execution Logs")
            full_log_text = "\n".join(full_logs)
            st.text_area("Logs", value=full_log_text, height=300)

        # 3. Downloads & GitHub Export
        st.markdown("---")
        col_dl_csv, col_dl_log, col_gh = st.columns(3)

        csv_data = trades_df.to_csv(index=False)
        log_data = "\n".join(full_logs)

        with col_dl_csv:
            st.download_button(
                label="📥 Download Trades CSV",
                data=csv_data,
                file_name=f"{strategy_name}_results.csv",
                mime="text/csv"
            )

        with col_dl_log:
            st.download_button(
                label="📜 Download Full Execution Log (.txt)",
                data=log_data,
                file_name=f"{strategy_name}_execution.log",
                mime="text/plain"
            )

        with col_gh:
            if st.button("🐙 Export Results + Logs to GitHub"):
                with st.spinner("Pushing CSV and Log files to GitHub..."):
                    ok, res = push_results_and_logs_to_github(
                        csv_content=csv_data,
                        log_content=log_data,
                        strategy_name=strategy_name,
                        pat_token=GITHUB_PAT,
                        repo_name=GITHUB_REPO,
                        branch=GITHUB_BRANCH
                    )
                    if ok:
                        st.success(f"✅ GitHub Commit Successful: {res}")
                    else:
                        st.error(f"❌ GitHub Commit Failed: {res}")

    except Exception as e:
        st.error(f"🚨 Critical Error: {e}")
        st.code(traceback.format_exc(), language="python")
