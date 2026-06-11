# push_to_live_sheets.py

import random
from exceptions import ThyrocarePipelineError
from services import GoogleSheetsService

def push_metrics_to_live_google_sheet():
    print("Initializing background connection via Native Service Layer...")
    sheets_service = GoogleSheetsService()
    
    all_rows = sheets_service.fetch_layout_matrix()
    if not all_rows:
        print("Sheet layout footprint is completely empty.")
        return

    headers = all_rows[0]
    col_idx_api = headers.index("API")
    col_idx_count = headers.index("Count")
    col_idx_5xx_pct = headers.index("5xx%")

    updated_rows_matrix = []

    print("Executing standalone pipeline metrics simulation...")
    for row in all_rows[1:]:
        api_name = row[col_idx_api].strip() if len(row) > col_idx_api else ""
        is_endpoint = any(api_name.upper().startswith(method) for method in ["GET", "POST", "PUT", "DELETE"])

        row_metrics = row[col_idx_count : col_idx_5xx_pct + 1]
        while len(row_metrics) < 6: row_metrics.append("")

        if is_endpoint:
            mock_count = random.randint(3000, 16000)
            mock_avg_rt = round(random.uniform(40.0, 110.0), 2)
            mock_p95_rt = round(mock_avg_rt * random.uniform(2.5, 3.4), 2)
            mock_4xx = random.randint(0, 8)
            mock_5xx = random.randint(0, 3) if random.random() > 0.1 else random.randint(12, 30)
            row_metrics = [mock_count, mock_avg_rt, mock_p95_rt, mock_4xx, mock_5xx, f"{round((mock_5xx/mock_count)*100,3)}%"]

        updated_rows_matrix.append(row_metrics)

    print("Flushing data directly to Google Core Servers via Native Transport Range Matrix...")
    start_letter = chr(65 + col_idx_count)
    end_letter = chr(65 + col_idx_5xx_pct)
    range_str = f"{start_letter}2:{end_letter}{len(all_rows)}"
    
    sheets_service.update_metrics_matrix(updated_rows_matrix, range_str)
    print("SUCCESS! The live spreadsheet has been cleanly updated.")

if __name__ == "__main__":
    try:
        push_metrics_to_live_google_sheet()
    except ThyrocarePipelineError as app_err:
        print(f"\n[PIPELINE HALTED]: {app_err.error_code} - {app_err.message}\n")
    except Exception as system_err:
        print(f"\n[CRITICAL ERROR]: {system_err}\n")