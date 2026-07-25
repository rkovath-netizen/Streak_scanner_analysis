import streamlit as st
import pandas as pd
from datetime import datetime
from strategy_engine import process_streak_batch
from metrics_calculator import calculate_advanced_metrics
from github_utils import push_csv_to_github

# Configure Streamlit Dashboard Page
st.set_page_config(page_title="Streak Scanner Backtest Engine", layout="wide")

st.title("📈 Streak Scanner Batch Backtest Engine")
st.markdown("Upload multiple **Zerodha Streak CSV exports**, run intraday backtests via **Upstox API**, and automatically archive reports to **GitHub**.")

# 1. Sidebar Configuration
st.sidebar.header("⚙️ Configuration Settings")

strategy_name = st.sidebar.text_input("Strategy Name", value="15_MT_Momentum")
strategy_type = st.sidebar.selectbox("Setup Direction", ["long", "short"])

tp_pct = st.sidebar.number_input("Target Profit (%)", min_value=0.5, max_value=50.0, value=5.0, step=0.5) / 100.0
sl_pct = st.sidebar.number_input("Stop Loss (%)", min_value=0.5, max_value=50.0, value=3.0, step=0.5) / 100.0
max_hold_days = st.sidebar.number_input("Max Holding Days", min_value=1, max_value=30, value=5, step=1)

# Retrieve tokens from secrets
upstox_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", "")
github_pat = st.secrets.get("GITHUB_PAT", "")
github_repo = st.secrets.get("GITHUB_REPO", "")
github_branch = st.secrets.get("GITHUB_BRANCH", "main")

if not upstox_token:
    st.error("⚠️ Upstox Access Token is missing from `.streamlit/secrets.toml`!")

# 2. File Upload Section
uploaded_files = st.file_uploader(
    "Upload Streak CSV Scanner Exports", 
    type=["csv"], 
    accept_multiple_files=True
)

if uploaded_files and st.button("🚀 Run Batch Backtest"):
    progress_bar = st.progress(0)
    status_text = st.empty()

    def update_progress(current, total, message):
        pct = int((current / total) * 100)
        progress_bar.progress(pct)
        status_text.text(f"[{current}/{total}] {message}")

    # Process signals
    with st.spinner("Processing trades and downloading Upstox intraday data..."):
        trades_df = process_streak_batch(
            csv_files=uploaded_files,
            upstox_token=upstox_token,
            strategy_type=strategy_type,
            tp_pct=tp_pct,
            sl_pct=sl_pct,
            max_hold_days=max_hold_days,
            progress_callback=update_progress
        )

    if trades_df.empty:
        st.error("No trades executed or unable to fetch market data.")
    else:
        st.success("✅ Backtest Execution Complete!")

        # Calculate stats
        overall_metrics, stock_summary = calculate_advanced_metrics(trades_df)

        # 3. Overall Portfolio Overview Metrics
        st.subheader("📊 Portfolio Performance Summary")
        m_cols = st.columns(4)
        m_cols[0].metric("Total Trades", overall_metrics["Total Trades"])
        m_cols[1].metric("Win Rate", f"{overall_metrics['Win Rate (%)']}%")
        m_cols[2].metric("Total PnL (Abs)", f"₹{overall_metrics['Total PnL (Abs)']}")
        m_cols[3].metric("Max Drawdown", f"₹{overall_metrics['Max Drawdown (Abs)']}")

        s_cols = st.columns(3)
        s_cols[0].metric("Avg Bars / Trade", f"{overall_metrics['Avg Bars in Trade']} bars")
        s_cols[1].metric("Bars 2-Sigma Range", overall_metrics["Bars 2-Sigma Range"])
        s_cols[2].metric("Daily Capital 2-Sigma Range", overall_metrics["Daily Capital 2-Sigma Range"])

        # 4. Detailed Tables
        st.subheader("📌 Stock Level Summary")
        st.dataframe(stock_summary, use_container_width=True)

        st.subheader("📄 Detailed Trade Log")
        st.dataframe(trades_df, use_container_width=True)

        # 5. Export and GitHub Sync
        csv_buffer = trades_df.to_csv(index=False)
        
        st.markdown("---")
        col_dl, col_gh = st.columns(2)
        
        timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_filename = f"{strategy_name.lower().replace(' ', '_')}_{timestamp_str}.csv"

        with col_dl:
            st.download_button(
                label="📥 Download CSV Output Locally",
                data=csv_buffer,
                file_name=export_filename,
                mime="text/csv"
            )

        with col_gh:
            if st.button("🐙 Commit Output CSV directly to GitHub"):
                if not github_pat or not github_repo:
                    st.error("GitHub PAT or Repo missing from Streamlit secrets.")
                else:
                    success, path_or_err = push_csv_to_github(
                        csv_content=csv_buffer,
                        strategy_name=strategy_name,
                        pat_token=github_pat,
                        repo_name=github_repo,
                        branch=github_branch
                    )
                    if success:
                        st.success(f"Successfully committed file to GitHub at `{path_or_err}`!")
                    else:
                        st.error(f"GitHub Commit failed: {path_or_err}")
