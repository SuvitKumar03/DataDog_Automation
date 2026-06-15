import json
import os
import time
import requests
from datetime import datetime, timezone
from openpyxl import Workbook
from config.datadog_config import DatadogConfigProperties

def run_bulk_metrics_report():
    # Load configuration parameters and Datadog authentication credentials
    config = DatadogConfigProperties()
    domain = config._get_base_domain()
    headers = config.get_standard_headers()
    
    ENV = "none"
    
    # Define targets for fixed window calculation (June 8, 2026 to June 14, 2026 UTC)
    start_dt = datetime(2026, 6, 8, 0, 0, 0, tzinfo=timezone.utc)
    end_dt = datetime(2026, 6, 14, 23, 59, 59, tzinfo=timezone.utc)
    
    START_EPOCH = int(start_dt.timestamp())
    END_EPOCH = int(end_dt.timestamp())
    TIME_WINDOW_SEC = END_EPOCH - START_EPOCH
    
    # Configure workspace directories
    endpoints_dir = "Enpoints"
    if not os.path.isdir(endpoints_dir):
        print(f"Error: Directory structure missing. Path '{endpoints_dir}' not found.")
        return
        
    metrics_url = f"https://api.{domain}/api/v1/query"
    excel_filename = "Metrics sheet 15 june 2026 demand + DSA.xlsx"
    columns = ["endpoint", "Requests", "Errors", "Avg Latency", "p95 Latency", "p99 Latency"]
    
    start_readable = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(START_EPOCH))
    end_readable = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(END_EPOCH))
    
    print("======================================================================")
    print("STARTING BULK REPORT EXTRACTION")
    print(f" Time Window Target : {start_readable} TO {end_readable}")
    print(f" Output Target File : {excel_filename}")
    print("======================================================================\n")

    # Initialize the primary excel workbook object
    wb = Workbook()
    is_initial_sheet = True

    # Retrieve and process all JSON sequence descriptor maps within the target folder
    json_files = [f for f in os.listdir(endpoints_dir) if f.endswith(".json")]
    
    if not json_files:
        print(f"Warning: No valid payload files discovered in directory '{endpoints_dir}'.")
        return

    for file_idx, json_file in enumerate(json_files, start=1):
        file_path = os.path.join(endpoints_dir, json_file)
        
        # Determine appropriate Sheet titles naming conventions based on filenames
        sheet_title = os.path.splitext(json_file)[0]
        
        with open(file_path, "r") as f:
            endpoints = json.load(f)
            
        print(f"--- Processing source file [{file_idx}/{len(json_files)}]: {json_file} -> Target Sheet: {sheet_title} ---")
        
        # Provision target active worksheets inside the compilation pipeline
        if is_initial_sheet:
            ws_current = wb.active
            ws_current.title = sheet_title
            is_initial_sheet = False
        else:
            ws_current = wb.create_sheet(title=sheet_title)
            
        ws_current.append(columns)

        # Parse every target endpoint definition configuration mapping rules
        for idx, target in enumerate(endpoints, start=1):
            name = target["name"]
            hash_id = target["hash"]
            service = target["service"]
            op = target["operation"]
            
            print(f" [{idx}/{len(endpoints)}] Fetching runtime data for metrics: {name}")
            
            queries = {
                "Count":  f"sum:trace.{op}.hits{{env:{ENV},service:{service},resource:{hash_id}}}.as_count()",
                "Errors": f"sum:trace.{op}.errors{{env:{ENV},service:{service},resource:{hash_id}}}.as_count()",
                "Avg":    f"avg:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(avg, {TIME_WINDOW_SEC})",
                "p95":    f"p95:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(avg, {TIME_WINDOW_SEC})",
                "p99":    f"p99:trace.{op}{{env:{ENV},service:{service},resource:{hash_id}}}.rollup(avg, {TIME_WINDOW_SEC})"
            }
            
            resolved_data = {"Count": "Null", "Errors": "Null", "Avg": "Null", "p95": "Null", "p99": "Null"}
            
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
                                else:
                                    resolved_data[key] = 0
                            continue
                            
                        pointlist = series[0].get("pointlist", [])
                        valid_values = [p[1] for p in pointlist if p[1] is not None]
                        
                        if valid_values:
                            if key in ["Count", "Errors"]:
                                resolved_data[key] = int(sum(valid_values))
                            else:
                                val = valid_values[-1] 
                                if val < 10.0: val *= 1000.0
                                resolved_data[key] = f"{val:.2f} ms"
                        else:
                            resolved_data[key] = 0 if key in ["Count", "Errors"] else "0.00 ms"
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

    # Commit workbook memory buffer state mapping allocations back down directly onto secondary local storage volumes
    wb.save(excel_filename)

    print("======================================================================")
    print(f" SUCCESS: Consolidated Multi-Sheet Report successfully stored at -> {os.path.abspath(excel_filename)}")
    print("======================================================================")

if __name__ == "__main__":
    run_bulk_metrics_report()