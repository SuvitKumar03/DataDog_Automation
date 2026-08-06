"""
Usage:
    DD_API_KEY=xxxx DD_APP_KEY=yyyy DD_SITE=datadoghq.com python APM_METRICS_WEEKLY.py
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

# Datadog API Client imports
from datadog_api_client import ApiClient, Configuration
from datadog_api_client.v2.api.metrics_api import MetricsApi
from datadog_api_client.v2.model.apm_metrics_data_source import ApmMetricsDataSource
from datadog_api_client.v2.model.apm_metrics_query import ApmMetricsQuery
from datadog_api_client.v2.model.apm_metrics_stat import ApmMetricsStat
from datadog_api_client.v2.model.query_formula import QueryFormula
from datadog_api_client.v2.model.scalar_formula_query_request import ScalarFormulaQueryRequest
from datadog_api_client.v2.model.scalar_formula_request import ScalarFormulaRequest
from datadog_api_client.v2.model.scalar_formula_request_attributes import ScalarFormulaRequestAttributes
from datadog_api_client.v2.model.scalar_formula_request_queries import ScalarFormulaRequestQueries
from datadog_api_client.v2.model.scalar_formula_request_type import ScalarFormulaRequestType


def specific_window():
    """
    Calculates millisecond timestamps for the explicit timeline:
    Jul 20, 12:00 am – Jul 26, 11:59 pm (UTC+05:30)
    
    Returns:
        from_ts (int): Start timestamp in milliseconds
        to_ts (int): End timestamp in milliseconds
        start_dt (datetime): Start datetime object
        end_dt (datetime): End datetime object
    """
    tz_offset = timezone(timedelta(hours=5, minutes=30))
    
    # Define start and end datetimes matching your timezone offset
    start_dt = datetime(2026, 7, 20, 0, 0, 0, tzinfo=tz_offset)
    end_dt = datetime(2026, 7, 26, 23, 59, 0, tzinfo=tz_offset)
    
    from_ts = int(start_dt.timestamp() * 1000)
    to_ts = int(end_dt.timestamp() * 1000)
    
    return from_ts, to_ts, start_dt, end_dt


def load_endpoints_by_file(folder_path: str = "Endpoints") -> dict:
    grouped_endpoints = {}
    base_path = Path(folder_path)
    
    if not base_path.exists():
        print(f"Error: The directory '{folder_path}' does not exist.")
        return grouped_endpoints

    for file_path in base_path.glob("*.json"):
        sheet_name = file_path.stem  # Gets filename without extension
        
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            endpoints = []
            if isinstance(data, list):
                endpoints.extend(data)
            elif isinstance(data, dict):
                endpoints.append(data)
                
            grouped_endpoints[sheet_name] = endpoints
                
    return grouped_endpoints


def build_request(endpoint: dict, from_ts: int, to_ts: int) -> ScalarFormulaQueryRequest:
    """Builds the formal Datadog Scalar Request body structure with all metrics."""
    common_kwargs = dict(
        data_source=ApmMetricsDataSource.APM_METRICS,
        service=endpoint["service"],
        operation_name=endpoint["operation"],
        resource_hash=endpoint["hash"],
    )

    return ScalarFormulaQueryRequest(
        data=ScalarFormulaRequest(
            attributes=ScalarFormulaRequestAttributes(
                _from=from_ts,
                to=to_ts,
                queries=ScalarFormulaRequestQueries(
                    [
                        ApmMetricsQuery(
                            name="p95",
                            stat=ApmMetricsStat.LATENCY_P95,
                            **common_kwargs,
                        ),
                        ApmMetricsQuery(
                            name="p99",
                            stat=ApmMetricsStat.LATENCY_P99,
                            **common_kwargs,
                        ),
                        ApmMetricsQuery(
                            name="count",
                            stat=ApmMetricsStat.HITS,
                            **common_kwargs,
                        ),
                        ApmMetricsQuery(
                            name="errors",
                            stat=ApmMetricsStat.ERRORS,
                            **common_kwargs,
                        ),
                        ApmMetricsQuery(
                            name="error_rate",
                            stat=ApmMetricsStat.ERROR_RATE,
                            **common_kwargs,
                        ),
                        ApmMetricsQuery(
                            name="avg_latency",
                            stat=ApmMetricsStat.LATENCY_AVG,
                            **common_kwargs,
                        ),
                    ]
                ),
                formulas=[
                    QueryFormula(formula="p95"),
                    QueryFormula(formula="p99"),
                    QueryFormula(formula="count"),
                    QueryFormula(formula="errors"),
                    QueryFormula(formula="error_rate"),
                    QueryFormula(formula="avg_latency"),
                ],
            ),
            type=ScalarFormulaRequestType.SCALAR_REQUEST,
        ),
    )


def extract_metric_values(response):
    data = response.to_dict()
    columns = data.get("data", {}).get("attributes", {}).get("columns", [])

    number_cols = [c for c in columns if c.get("type") == "number"]
    
    results_map = {}
    for col in number_cols:
        name = col.get("name")
        values = col.get("values", [])
        val = values[0] if values else None
        if name:
            results_map[name] = val

    def get_val(idx):
        if idx < len(number_cols):
            vals = number_cols[idx].get("values", [])
            return vals[0] if vals else None
        return None

    return {
        "p95": results_map.get("p95", get_val(0)),
        "p99": results_map.get("p99", get_val(1)),
        "count": results_map.get("count", get_val(2)),
        "errors": results_map.get("errors", get_val(3)),
        "error_rate": results_map.get("error_rate", get_val(4)),
        "avg_latency": results_map.get("avg_latency", get_val(5)),
    }


def convert_sec_to_ms(val):
    if val is not None:
        return round(val * 1000, 2)
    return None


def main():
    folder_name = "Endpoints"
    
    from_ts, to_ts, start_dt, end_dt = specific_window()

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")
    excel_filename = f"APM_Metrics_{start_str}_to_{end_str}.xlsx"

    # Derive dynamic Excel sheet name from dates (e.g., "Metrics_27Jul_02Aug")
    sheet_start_fmt = start_dt.strftime("%d%b")
    sheet_end_fmt = end_dt.strftime("%d%b")
    dynamic_sheet_name = f"Metrics_{sheet_start_fmt}_{sheet_end_fmt}"[:31]

    grouped_endpoints = load_endpoints_by_file(folder_name)
    if not grouped_endpoints:
        print("No endpoint JSON files found. Exiting.")
        return

    configuration = Configuration()

    with ApiClient(configuration) as api_client:
        api_instance = MetricsApi(api_client)

        with pd.ExcelWriter(excel_filename, engine="openpyxl") as writer:
            
            for file_group, endpoints in grouped_endpoints.items():
                print(f"Processing sheet '{file_group}' with {len(endpoints)} endpoint(s)...")
                file_results = []

                for endpoint in endpoints:
                    body = build_request(endpoint, from_ts, to_ts)
                    response = api_instance.query_scalar_data(body=body)
                    metrics = extract_metric_values(response)

                    # Conversion step: multiply latency metrics (sec) by 1000 -> ms
                    p95_ms = convert_sec_to_ms(metrics["p95"])
                    p99_ms = convert_sec_to_ms(metrics["p99"])
                    avg_latency_ms = convert_sec_to_ms(metrics["avg_latency"])

                    # 1. Default errors to 0 if None
                    errors_count = metrics["errors"] if metrics["errors"] is not None else 0

                    # 2. Convert error_rate fraction to percentage (multiply by 100)
                    error_rate_pct = round(metrics["error_rate"] * 100, 2) if metrics["error_rate"] is not None else 0.0

                    # 3. Exact column ordering: service, endpoint, hash, count, avg_latency, p95, p99, errors, error_rate (%)
                    file_results.append(
                        {
                            "service": endpoint.get("service"),
                            "endpoint": endpoint.get("name"),
                            "resource_hash": endpoint.get("hash"),
                            "count": metrics["count"] if metrics["count"] is not None else 0,
                            "avg_latency (ms)": avg_latency_ms,
                            "p95 (ms)": p95_ms,
                            "p99 (ms)": p99_ms,
                            "errors": errors_count,
                            "error_rate (%)": error_rate_pct,
                        }
                    )

                df = pd.DataFrame(file_results)
                sheet_label = f"{file_group}_{sheet_start_fmt}_{sheet_end_fmt}"[:31] if len(grouped_endpoints) > 1 else dynamic_sheet_name
                df.to_excel(writer, sheet_name=sheet_label, index=False)

    print(f"\nSuccess! Exported metrics for {start_str} to {end_str} across {len(grouped_endpoints)} tabs in '{excel_filename}'.")


if __name__ == "__main__":
    main()