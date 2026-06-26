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
    
    # Define the hourly rollup interval (3600 seconds = 1 hour)
    HOURLY_ROLLUP_SEC = 3600
    
    endpoints_dir = "Enpoints"
    if not os.path.isdir(endpoints_dir):
        print(f"Error: Directory structure missing. Path '{endpoints_dir}' not found.")
        return
        
    metrics_url = f"https://api.{domain}/api/v1/query"
    excel_filename = "Metrics sheet 15 june 2026 demand + DSA.xlsx"
    columns = ["endpoint", "Requests", "Errors", "Avg Latency", "p95 Latency", "p99 Latency"]
    
    # ============================================
    # EXCEL SHEET CODE - COMMENTED OUT FOR NOW
    # ============================================
    # wb = Workbook()
    # is_initial_sheet = True

    json_files = [f for f in os.listdir(endpoints_dir) if f.endswith(".json")]
    if not json_files:
        print(f"Warning: No valid configuration files found in '{endpoints_dir}'.")
        return

    # Print header for terminal output
    print("\n" + "="*120)
    print(f"{'Endpoint':<40} {'Requests':<15} {'Errors':<12} {'Avg (ms)':<12} {'p95 (ms)':<12} {'p99 (ms)':<12}")
    print("="*120)

    for file_idx, json_file in enumerate(json_files, start=1):
        file_path = os.path.join(endpoints_dir, json_file)
        sheet_title = os.path.splitext(json_file)[0]
        
        with open(file_path, "r") as f:
            endpoints = json.load(f)
            
        print(f"\n--- Processing source file [{file_idx}/{len(json_files)}]: {json_file} -> Sheet: {sheet_title} ---")
        
        # ============================================
        # EXCEL SHEET CODE - COMMENTED OUT FOR NOW
        # ============================================
        # if is_initial_sheet:
        #     ws_current = wb.active
        #     ws_current.title = sheet_title
        #     is_initial_sheet = False
        # else:
        #     ws_current = wb.create_sheet(title=sheet_title)
        # ws_current.append(columns)

        for idx, target in enumerate(endpoints, start=1):
            name = target["name"]
            hash_id = target["hash"]
            service = target["service"]
            op = target["operation"]
            
            print(f" [{idx}/{len(endpoints)}] Fetching metrics for: {name}")
            
            # CRITICAL FIX: For p95/p99, we need nested rollup
            queries = {
                "Count":  f"sum:trace.{op}.hits{{env:{ENV},service:{service},resource:{hash_id}}}.as_count()",
                "Errors": f"sum:trace.{op}.errors{{env:{ENV},service:{service},resource:{hash_id}}}.as_count()",
                "Avg":    f"avg:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(avg, {TIME_WINDOW_SEC})",
                # FIXED: Simplified p95 query - Datadog handles the time aggregation internally for distributions
                "p95":    f"p95:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup({TIME_WINDOW_SEC})",
                # FIXED: Simplified p99 query
                "p99":    f"p99:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup({TIME_WINDOW_SEC})"
            }
            
            resolved_data = {"Count": 0, "Errors": 0, "Avg": "0.00 ms", "p95": "0.00 ms", "p99": "0.00 ms"}
            
            for key, query_str in queries.items():
                params = {"from": START_EPOCH, "to": END_EPOCH, "query": query_str}
                try:
                    res = requests.get(metrics_url, headers=headers, params=params, timeout=10)
                    if res.status_code == 200:
                        series = res.json().get("series", [])
                        
                        if not series:
                            # Fallback for Errors: check for error:1 tag
                            if key == "Errors":
                                print(f"  -> No errors found in main query, checking error:1 tag for {name}")
                                fb_query = f"sum:trace.{op}.hits{{env:{ENV},service:{service},resource:{hash_id},error:1}}.as_count()"
                                fb_resp = requests.get(metrics_url, headers=headers, params={"from": START_EPOCH, "to": END_EPOCH, "query": fb_query}, timeout=10)
                                if fb_resp.status_code == 200:
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
                                # For Avg: take the average of all valid values (or the last one if there's only one)
                                final_val = sum(valid_values) / len(valid_values)
                                if final_val < 10.0 and final_val > 0:
                                    final_val *= 1000.0
                                resolved_data[key] = f"{final_val:.2f} ms"
                            else:
                                # FIXED: For p95 and p99 with rollup, we should get a single value
                                # But sometimes Datadog returns multiple points; take the last one
                                # or if there are multiple, take the one that represents the full time range
                                final_val = valid_values[-1] if valid_values else 0
                                
                                # If we got 0 but there might be data, check if we need to sum instead
                                if final_val == 0 and len(valid_values) > 1:
                                    # Sometimes the values are distributed across multiple points
                                    # Try taking the max or average
                                    final_val = sum(valid_values) / len(valid_values)
                                
                                # Unit scaling: Datadog returns latency in seconds for trace metrics
                                # If value is less than 10, it's likely in seconds, convert to ms
                                if final_val < 10.0 and final_val > 0:
                                    final_val *= 1000.0
                                resolved_data[key] = f"{final_val:.2f} ms"
                                
                                # DEBUG: Print raw values to help diagnose
                                print(f"    DEBUG {key}: raw values = {valid_values}, final = {final_val}")
                except Exception as e:
                    print(f"  -> Error fetching {key} for {name}: {str(e)}")
                    pass
            
            count_val = f"{resolved_data['Count']:,}" if isinstance(resolved_data['Count'], int) else resolved_data['Count']
            error_val = f"{resolved_data['Errors']:,}" if isinstance(resolved_data['Errors'], int) else resolved_data['Errors']

            # ============================================
            # TERMINAL OUTPUT - PRINT EACH ROW
            # ============================================
            print(f"{name:<40} {count_val:<15} {error_val:<12} {resolved_data['Avg']:<12} {resolved_data['p95']:<12} {resolved_data['p99']:<12}")

            # ============================================
            # EXCEL SHEET CODE - COMMENTED OUT FOR NOW
            # ============================================
            # row_data = [
            #     name,
            #     count_val,
            #     error_val,
            #     resolved_data["Avg"],
            #     resolved_data["p95"],
            #     resolved_data["p99"]
            # ]
            # ws_current.append(row_data)
            
        print()

    # ============================================
    # EXCEL SHEET CODE - COMMENTED OUT FOR NOW
    # ============================================
    # wb.save(excel_filename)
    # print("======================================================================")
    # print(f" SUCCESS: High-Accuracy Multi-Sheet Report saved -> {os.path.abspath(excel_filename)}")
    # print("======================================================================")

    print("="*120)
    print(" ✅ All metrics fetched and displayed in terminal above")
    print("="*120)

if __name__ == "__main__":
    run_bulk_metrics_report()