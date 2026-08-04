import streamlit as st
import pandas as pd
import io
from datetime import datetime
from strategy_engine import process_streak_comparative_batch
from metrics_calculator import generate_comparison_metrics
from github_utils import push_csv_to_github
from upstox_data import get_instrument_df

st.set_page_config(page_title="Multi-Strategy Options Backtester", layout="wide")
st.title("📈 Comparative Options Hedge Backtester")

st.sidebar.header("⚙️ Configuration")
strategy_name = st.sidebar.text_input("Report Name", value="15_MT_Momentum_Compare")
setup_direction = st.sidebar.selectbox("Scanner Direction (Spot Exit Logic)", ["Bullish", "Bearish"])

tp_pct = st.sidebar.number_input("Underlying Target Profit (%)", min_value=0.5, value=5.0, step=0.5) / 100.0
sl_pct = st.sidebar.number_input("Underlying Stop Loss (%)", min_value=0.5, value=3.0, step=0.5) / 100.0
max_hold_days = st.sidebar.number_input("Max Holding Days", min_value=1, value=5, step=1)

upstox_token = st.secrets.get("UPSTOX_ACCESS_TOKEN", None)
github_pat = st.secrets.get("GITHUB_PAT", None)
github_repo = st.secrets.get("GITHUB_REPO", None)
github_branch = st.secrets.get("GITHUB_BRANCH", "main")

with st.sidebar.expander("🔑 Secrets Status", expanded=False):
    st.write("Upstox Token:", "✅ Detected" if upstox_token else "❌ Missing")
    st.write("GitHub PAT:", "✅ Detected" if github_pat else "❌ Missing")
    st.write("GitHub Repo:", github_repo if github_repo else "❌ Missing")

if st.sidebar.button("🧪 Test Upstox Connection"):
    with st.spinner("Downloading/Checking Instrument Master..."):
        df_inst = get_instrument_df()
        if not df_inst.empty:
            st.sidebar.success(f"✅ Upstox Connected! Loaded {len(df_inst)} instruments.")
        else:
            st.sidebar.error("❌ Upstox connection failed.")

log_expander = st.expander("🛠️ Real-Time Debug & Execution Logs", expanded=True)
log_box = log_expander.empty()
log_messages = []

def ui_log(msg):
    timestamp = datetime.now().strftime("%H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    log_messages.append(formatted_msg)
    log_box.code("\n".join(log_messages[-25:]), language="text")

tab1, tab2 = st.tabs(["📁 File Uploader & Diagnostics", "📝 Paste CSV (Mobile Fallback)"])

files_to_process = None
run_backtest = False

with tab1:
    st.markdown("### Step 1: Upload Files")
    
    # NEW: The Diagnostic Input
    expected_files = st.number_input("How many files are you selecting in the browser?", min_value=1, value=11, step=1)
    
    uploaded_files = st.file_uploader("Upload Streak CSVs (OR a single .zip file)", accept_multiple_files=True)
    
    if uploaded_files:
        received_count = len(uploaded_files)
        
        # NEW: Diagnostic Engine Output
        st.markdown("---")
        st.markdown("### 🔬 Upload Diagnostics")
        
        if received_count == expected_files:
            st.success(f"✅ Perfect Match! You selected {expected_files} files and Streamlit received {received_count} files.")
        else:
            st.error(f"⚠️ MISMATCH DETECTED: You selected {expected_files} files, but the server only received {received_count} files. The browser or OS dropped {expected_files - received_count} files during the upload transfer.")
            
        with st.expander("👀 View Raw Data Received by Server", expanded=True):
            for i, f in enumerate(uploaded_files):
                st.code(f"File {i+1}:\nName: {f.name}\nSize: {f.size} bytes\nType: {f.type}", language="text")
        st.markdown("---")
    
    if st.button("🚀 Run Backtest (Uploaded Files)"):
        files_to_process = uploaded_files
        run_backtest = True

with tab2:
    pasted_csv = st.text_area("Paste Streak CSV data here:", height=200, placeholder="s_no,seg_sym,sector,ltp,change,volume,time\n1,NSE:RELIANCE,,2500,1.5,50000,2026-07-22 09:30:00")
    
    if st.button("🚀 Run Backtest (Pasted Data)"):
        if pasted_csv.strip():
            mock_file = io.StringIO(pasted_csv)
            mock_file.name = "pasted_mobile_data.csv"
            files_to_process = [mock_file]
            run_backtest = True
        else:
            st.error("⚠️ Please paste some CSV data first.")

if run_backtest:
    if not files_to_process:
        st.error("⚠️ Please upload a file or paste CSV data before running.")
    elif not upstox_token:
        st.error("❌ Cannot proceed: UPSTOX_ACCESS_TOKEN is missing from Secrets.")
    else:
        progress_bar = st.progress(0)
        status_text = st.empty()

        def update_progress(current, total, message):
            progress_bar.progress(int((current / total) * 100))
            status_text.text(f"[{current}/{total}] {message}")

        ui_log("Starting backtest run...")
        
        trades_df = process_streak_comparative_batch(
            csv_files=files_to_process, upstox_token=upstox_token,
            setup_direction=setup_direction, tp_pct=tp_pct, sl_pct=sl_pct,
            max_hold_days=max_hold_days, progress_callback=update_progress,
            log_func=ui_log
        )

        if trades_df.empty:
            st.error("❌ No valid trades executed. Check the Debug Logs above.")
        else:
            st.success("✅ Comparative Backtest Complete!")
            
            comparison_df = generate_comparison_metrics(trades_df)

            st.subheader("📊 Strategy Performance Comparison")
            st.dataframe(comparison_df, use_container_width=True)

            st.subheader("📄 Detailed Trade Log")
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
