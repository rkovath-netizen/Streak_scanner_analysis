import streamlit as st
import pandas as pd
from datetime import datetime
from strategy_engine import process_streak_comparative_batch
from metrics_calculator import generate_comparison_metrics
from github_utils import push_csv_to_github

st.set_page_config(page_title="Multi-Strategy Options Backtester", layout="wide")
st.title("📈 Comparative Options Hedge Backtester")
st.markdown("Upload Streak signals to instantly simulate and compare **Naked Options, Straddles, OTM1 Hedges, and OTM2 Hedges** side-by-side.")

st.sidebar.header("⚙️ Configuration")
strategy_name = st.sidebar.text_input("Report Name", value="15_MT_Momentum_Compare")

# The Setup Direction determines if the Spot Asset looks for +5% target (Bullish) or -5% target (Bearish)
setup_direction = st.sidebar.selectbox("Scanner Direction (Spot Exit Logic)", ["Bullish", "Bearish"])

tp_pct = st.sidebar.number_input("Underlying Target Profit (%)", min_value=0.5, value=5.0, step=0.5) / 100.0
sl_pct = st.sidebar.number_input("Underlying Stop Loss (%)", min_value=0.5, value=3.0, step=0.5) / 100.0
max_hold_days = st.sidebar.number_input("Max Holding Days", min_value=1, value=5, step=1)

upstox_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", None)
github_pat = st.secrets.get("GITHUB_PAT", None)
github_repo = st.secrets.get("GITHUB_REPO", None)
github_branch = st.secrets.get("GITHUB_BRANCH", "main")

if not github_pat or not upstox_token:
    st.sidebar.warning("⚠️ Missing API tokens in Streamlit secrets settings.")

uploaded_files = st.file_uploader("Upload Streak CSV Scanner Exports", type=["csv"], accept_multiple_files=True)

if uploaded_files and st.button("🚀 Run Comparative Backtest"):
    if not upstox_token:
        st.error("Cannot proceed: UPSTOX_ACCESS_TOKEN is not set.")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(current, total, message):
            progress_bar.progress(int((current / total) * 100))
            status_text.text(f"[{current}/{total}] {message}")

        with st.spinner("Fetching Spot & Option Chains. Simulating all hedges..."):
            trades_df = process_streak_comparative_batch(
                csv_files=uploaded_files, upstox_token=upstox_token,
                setup_direction=setup_direction, tp_pct=tp_pct, sl_pct=sl_pct,
                max_hold_days=max_hold_days, progress_callback=update_progress
            )

        if trades_df.empty:
            st.error("No trades executed or market data missing.")
        else:
            st.success("✅ Comparative Backtest Complete!")
            
            # Generate Comparison Table
            comparison_df = generate_comparison_metrics(trades_df)

            st.subheader("📊 Strategy Performance Comparison (All Variants)")
            st.dataframe(comparison_df, use_container_width=True)

            st.subheader("📄 Detailed Trade Log (Side-by-Side PnL)")
            st.dataframe(trades_df, use_container_width=True)

            csv_buffer = trades_df.to_csv(index=False)
            st.markdown("---")
            col1, col2 = st.columns(2)
            
            timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
            export_filename = f"{strategy_name.lower()}_{timestamp_str}.csv"

            with col1:
                st.download_button("📥 Download Full CSV", csv_buffer, export_filename, "text/csv")
            with col2:
                if github_pat and github_repo:
                    with st.spinner("Archiving comparative report to GitHub `output/`..."):
                        success, path = push_csv_to_github(csv_buffer, strategy_name, github_pat, github_repo, github_branch)
                        if success:
                            st.success(f"✅ Auto-Committed to `{path}`!")
                        else:
                            st.error("❌ GitHub Commit failed.")
