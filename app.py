# app.py

import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta

# Import our decoupled components
from exceptions import ThyrocarePipelineError
from services import GoogleSheetsService, DatadogMetricsService

st.set_page_config(page_title="Thyrocare Metrics Sync Engine", page_icon="📊", layout="wide")

st.markdown("""
    <style>
    .block-container {padding-top: 1.5rem;}
    .status-card {background-color: #1e293b; padding: 1rem; border-radius: 8px; border: 1px solid #334155;}
    </style>
    """, unsafe_allow_html=True)

# Sidebar Controller Logic
st.sidebar.title("Sync Controller")
today = datetime.now()
date_range = st.sidebar.date_input("Operational Date Scope", [today - timedelta(days=7), today])
start_time = st.sidebar.time_input("Execution Start Boundary", datetime.strptime("00:00", "%H:%M").time())
end_time = st.sidebar.time_input("Execution End Boundary", datetime.strptime("23:59", "%H:%M").time())

# UI Helper functions that route to our native service engines
@st.cache_data(ttl=60)
def load_ui_layout():
    sheets_engine = GoogleSheetsService()
    return sheets_engine.fetch_layout_matrix()

def run_ui_synchronization(all_rows, start_epoch, end_epoch, progress_bar, status_text):
    headers = all_rows[0]
    col_idx_api = headers.index("API")
    col_idx_count = headers.index("Count")
    col_idx_5xx_pct = headers.index("5xx%")
    
    dd_service = DatadogMetricsService()
    sheets_service = GoogleSheetsService()
    updated_rows_matrix = []

    for i, row in enumerate(all_rows[1:], start=2):
        api_name = row[col_idx_api].strip() if len(row) > col_idx_api else ""
        is_endpoint = any(api_name.upper().startswith(m) for m in ["GET", "POST", "PUT", "DELETE"])
        
        row_metrics = row[col_idx_count : col_idx_5xx_pct + 1]
        while len(row_metrics) < 6: row_metrics.append("")

        if is_endpoint:
            status_text.markdown(f"Polling metrics from Datadog: `{api_name}`")
            m = dd_service.fetch_endpoint_telemetry(api_name, start_epoch, end_epoch)
            row_metrics = [m["count"], m["avg_rt"], m["p95_rt"], m["errors_4xx"], m["errors_5xx"], m["pct_5xx"]]
            time.sleep(0.02)
            
        updated_rows_matrix.append(row_metrics)
        progress_bar.progress(int(((i - 1) / (len(all_rows) - 1)) * 100))

    status_text.markdown("Transmitting metrics directly to Google Cloud Core...")
    start_letter = chr(65 + col_idx_count)
    end_letter = chr(65 + col_idx_5xx_pct)
    range_string = f"{start_letter}2:{end_letter}{len(all_rows)}"
    
    sheets_service.update_metrics_matrix(updated_rows_matrix, range_string)

# Main Application Frame rendering
st.title("Thyrocare Core APM Sync Engine")
st.caption("Modular Enterprise Integration Dashboard")
st.markdown("---")

if len(date_range) == 2:
    epoch_start = int(datetime.combine(date_range[0], start_time).timestamp())
    epoch_end = int(datetime.combine(date_range[1], end_time).timestamp())

    try:
        all_rows = load_ui_layout()
        detected_apis = [row[0].strip() for row in all_rows[1:] if row and any(row[0].strip().upper().startswith(m) for m in ["GET", "POST", "PUT", "DELETE"])]
        
        with st.expander(f"Discovered Layout Footprint ({len(detected_apis)} API Endpoints Identified)"):
            st.dataframe(pd.DataFrame(detected_apis, columns=["Target Routing Paths"]), use_container_width=True, hide_index=True)
            
        if st.button("Run Analytics Sync Pipeline", use_container_width=True, type="primary"):
            p_bar = st.progress(0)
            s_text = st.empty()
            run_ui_synchronization(all_rows, epoch_start, epoch_end, p_bar, s_text)
            s_text.empty()
            st.success("Synchronization complete! Google Sheet has been natively updated.")
            st.cache_data.clear()
            
    except ThyrocarePipelineError as e:
        st.error(f"Execution Failed: {e.error_code} - {e.message}")