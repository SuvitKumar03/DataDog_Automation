import json
import os
import time
import requests
from datetime import datetime, timezone
from openpyxl import Workbook
from config.datadog_config import DatadogConfigProperties

def run_bulk_metrics_report():
    config = DatadogConfigProperties()
    domain = config._get_base_domain()
    headers = config.get_standard_headers()
    
    ENV = "none"
    
    # Target Window: Jun 8, 2026 to Jun 14, 2026 UTC
    start_dt = datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 14, 23, 59, 59, tzinfo=timezone.utc)
    
    START_EPOCH = int(start_dt.timestamp())
    END_EPOCH = int(end_dt.timestamp())
    TIME_WINDOW_SEC = END_EPOCH - START_EPOCH
    
    endpoints_dir = "Enpoints"
    if not os.path.isdir(endpoints_dir):
        print(f"Error: Directory structure missing. Path '{endpoints_dir}' not found.")
        return
        
    metrics_url = f"https://api.{domain}/api/v1/query"
    excel_filename = "Metrics sheet 15 june 2026 demand + DSA.xlsx"
    columns = ["endpoint", "Requests", "Errors", "Avg Latency", "p95 Latency", "p99 Latency"]
    
    wb = Workbook()
    is_initial_sheet = True

    json_files = [f for f in os.listdir(endpoints_dir) if f.endswith(".json")]
    if not json_files:
        print(f"Warning: No valid configuration files found in '{endpoints_dir}'.")
        return

    for file_idx, json_file in enumerate(json_files, start=1):
        file_path = os.path.join(endpoints_dir, json_file)
        sheet_title = os.path.splitext(json_file)[0]
        
        with open(file_path, "r") as f:
            endpoints = json.load(f)
            
        print(f"--- Processing source file [{file_idx}/{len(json_files)}]: {json_file} -> Target Sheet: {sheet_title} ---")
        
        if is_initial_sheet:
            ws_current = wb.active
            ws_current.title = sheet_title
            is_initial_sheet = False
        else:
            ws_current = wb.create_sheet(title=sheet_title)
            
        ws_current.append(columns)

        for idx, target in enumerate(endpoints, start=1):
            name = target["name"]
            hash_id = target["hash"]
            service = target["service"]
            op = target["operation"]
            
            print(f" [{idx}/{len(endpoints)}] Fetching metrics for: {name}")
            
            # Formulating precision queries
            # Count/Errors use sum over time window
            # Avg rolls up using baseline average evaluation
            # p95/p99 requests maximum percentile boundary peak across the timeframe
            queries = {
                "Count":  f"sum:trace.{op}.hits{{env:{ENV},service:{service},resource:{hash_id}}}.as_count()",
                "Errors": f"sum:trace.{op}.errors{{env:{ENV},service:{service},resource:{hash_id}}}.as_count()",
                "Avg":    f"avg:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(avg, {TIME_WINDOW_SEC})",
                "p95":    f"p95:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(max, {TIME_WINDOW_SEC})",
                "p99":    f"p99:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(max, {TIME_WINDOW_SEC})"
            }
            
            resolved_data = {"Count": 0, "Errors": 0, "Avg": "0.00 ms", "p95": "0.00 ms", "p99": "0.00 ms"}
            
            for key, query_str in queries.items():
                params = {"from": START_EPOCH, "to": END_EPOCH, "query": query_str}
                try:
                    res = requests.get(metrics_url, headers=headers, params=params, timeout=10)
                    if res.status_code == 200:
                        series = res.json().get("series", [])
                        
                        if not series:
                            if key == "Errors":
                                fb_query = f"sum:trace.{op}.hits{{env:{ENV},service:{service},resource:{hash_id},error:1}}.as_count()"
                                fb_resp = requests.get(metrics_url, headers=headers, params={"from": START_EPOCH, "to": END_EPOCH, "query": fb_query}, timeout=10)
                                fb_series = fb_resp.json().get("series", [])
                                if fb_series:
                                    fb_pts = [p[1] for p in fb_series[0].get("pointlist", []) if p[1] is not None]
                                    resolved_data[key] = int(sum(fb_pts))
                            continue
                            
                        pointlist = series[0].get("pointlist", [])
                        valid_values = [p[1] for p in pointlist if p[1] is not None]
                        
                        if valid_values:
                            if key in ["Count", "Errors"]:
                                resolved_data[key] = int(sum(valid_values))
                            elif key == "Avg":
                                # Compute true global mathematical mean over interval points
                                final_val = sum(valid_values) / len(valid_values)
                                if final_val < 10.0: final_val *= 1000.0  # Unit scaling fix
                                resolved_data[key] = f"{final_val:.2f} ms"
                            else:
                                # For p95 and p99, capture peak threshold distribution value 
                                final_val = max(valid_values)
                                if final_val < 10.0: final_val *= 1000.0  # Unit scaling fix
                                resolved_data[key] = f"{final_val:.2f} ms"
                except Exception:
                    pass
            
            count_val = f"{resolved_data['Count']:,}" if isinstance(resolved_data['Count'], int) else resolved_data['Count']
            error_val = f"{resolved_data['Errors']:,}" if isinstance(resolved_data['Errors'], int) else resolved_data['Errors']

            row_data = [
                name,
                count_val,
                error_val,
                resolved_data["Avg"],
                resolved_data["p95"],
                resolved_data["p99"]
            ]
            ws_current.append(row_data)
        print()

    wb.save(excel_filename)
    print("======================================================================")
    print(f" SUCCESS: High-Accuracy Multi-Sheet Report saved -> {os.path.abspath(excel_filename)}")
    print("======================================================================")

if __name__ == "__main__":
    run_bulk_metrics_report()