"""
Extracts 4xx / 5xx request-count breakdown per endpoint from Datadog APM
trace metrics, using group_by(http.status_code) -- NOT query_filter, which
does not match anything on this data source (confirmed against live data).

Usage:
    DD_API_KEY=xxxx DD_APP_KEY=yyyy DD_SITE=datadoghq.com python 4xx_5xx_breakdown.py
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd

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
    Aug 10, 12:00 am - Aug 16, 11:59 pm (UTC+05:30)
    Change these dates to whichever week you're reporting on.
    """
    tz_offset = timezone(timedelta(hours=5, minutes=30))

    start_dt = datetime(2026, 8, 17, 0, 0, 0, tzinfo=tz_offset)
    end_dt = datetime(2026, 8, 23, 23, 59, 0, tzinfo=tz_offset)

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
        sheet_name = file_path.stem

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            endpoints = []

            if isinstance(data, list):
                endpoints.extend(data)
            elif isinstance(data, dict):
                endpoints.append(data)

            grouped_endpoints[sheet_name] = endpoints

    return grouped_endpoints


def build_status_code_request(
    endpoint: dict,
    from_ts: int,
    to_ts: int
) -> ScalarFormulaQueryRequest:
    """
    http.status_code is a valid group_by dimension on the `hits` stat
    (confirmed live: grouping a known endpoint's hits by http.status_code
    returned 503:31, 201:5, 200:182926 -- matching that endpoint's
    hits_unfiltered and errors_native exactly). So we group hits by status
    code here and bucket 4xx/5xx ourselves in extract_status_class_breakdown().
    """
    return ScalarFormulaQueryRequest(
        data=ScalarFormulaRequest(
            attributes=ScalarFormulaRequestAttributes(
                _from=from_ts,
                to=to_ts,
                queries=ScalarFormulaRequestQueries(
                    [
                        ApmMetricsQuery(
                            name="hits_by_status",
                            stat=ApmMetricsStat.HITS,
                            group_by=["http.status_code"],
                            data_source=ApmMetricsDataSource.APM_METRICS,
                            service=endpoint["service"],
                            operation_name=endpoint["operation"],
                            resource_hash=endpoint["hash"],
                        ),
                    ]
                ),
                formulas=[QueryFormula(formula="hits_by_status")],
            ),
            type=ScalarFormulaRequestType.SCALAR_REQUEST,
        ),
    )


def extract_status_class_breakdown(response) -> dict:
    """
    Buckets a group_by(http.status_code) Scalar API response into 4xx/5xx
    totals. The response has a "group" column (status code per row, e.g.
    "200", "404", "503", or "N/A" for spans with no status code) and a
    parallel "number" column with the hit count for that code.
    """
    data = response.to_dict()
    columns = data.get("data", {}).get("attributes", {}).get("columns", [])

    group_col = next((c for c in columns if c.get("type") == "group"), None)
    number_col = next((c for c in columns if c.get("type") == "number"), None)

    totals = {"4xx": 0, "5xx": 0}

    if group_col is None or number_col is None:
        return totals

    for code_group, hit_count in zip(
        group_col.get("values", []),
        number_col.get("values", [])
    ):
        code = code_group[0] if code_group else None

        if not code or not code.isdigit() or hit_count is None:
            continue

        if code.startswith("4"):
            totals["4xx"] += hit_count
        elif code.startswith("5"):
            totals["5xx"] += hit_count

    return totals


def main():
    folder_name = "Endpoints"

    from_ts, to_ts, start_dt, end_dt = specific_window()

    start_str = start_dt.strftime("%Y-%m-%d")
    end_str = end_dt.strftime("%Y-%m-%d")
    excel_filename = f"4xx_5xx_Breakdown_{start_str}_to_{end_str}.xlsx"

    sheet_start_fmt = start_dt.strftime("%d%b")
    sheet_end_fmt = end_dt.strftime("%d%b")
    dynamic_sheet_name = f"Status_{sheet_start_fmt}_{sheet_end_fmt}"[:31]

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
                    status_body = build_status_code_request(endpoint, from_ts, to_ts)
                    status_response = api_instance.query_scalar_data(body=status_body)
                    breakdown = extract_status_class_breakdown(status_response)

                    file_results.append(
                        {
                            "service": endpoint.get("service"),
                            "endpoint": endpoint.get("name"),
                            "resource_hash": endpoint.get("hash"),
                            "4xx": breakdown["4xx"],
                            "5xx": breakdown["5xx"],
                        }
                    )

                df = pd.DataFrame(file_results)

                sheet_label = (
                    f"{file_group}_{sheet_start_fmt}_{sheet_end_fmt}"
                )[:31] if len(grouped_endpoints) > 1 else dynamic_sheet_name

                df.to_excel(writer, sheet_name=sheet_label, index=False)

    print(f"\nSuccess! Exported 4xx/5xx breakdown for {start_str} to {end_str} in '{excel_filename}'.")


if __name__ == "__main__":
    main()