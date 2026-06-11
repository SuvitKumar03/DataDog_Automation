import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional, Dict, Any, List 
from config.datadog_config import DatadogConfigProperties
from model.metrics_dto import EndpointMetricsDTO

class DatadogMetricsService:
    def __init__(self, config_properties: DatadogConfigProperties):
        self.config = config_properties

    def _execute_single_query(self, query_string: str, start_epoch: int, end_epoch: int) -> Optional[Dict[str, Any]]:
        params = {"from": start_epoch, "to": end_epoch, "query": query_string}
        try:
            response = requests.get(self.config.get_v1_query_url(), headers=self.config.get_standard_headers(), params=params, timeout=15)
            if response.status_code == 200:
                return response.json()
        except requests.exceptions.RequestException:
            pass
        return None

    def _fetch_java_trace_analytics(self, env: str, service: str, resource: str, start_epoch: int, end_epoch: int) -> Optional[EndpointMetricsDTO]:
        """
        Directly reads trace log distributions using Datadog's official, proven public 
        search gateway, bypassing strict aggregator validation restrictions.
        """
        # Using the official public search path that cleared the 404 block
        url = f"https://{self.config._get_base_domain()}/api/v2/spans/events/search"
        headers = self.config.get_standard_headers()
        
        # Public search schema layout
        payload = {
            "data": {
                "type": "search_request",
                "attributes": {
                    "filter": {
                        "from": f"{start_epoch}000",
                        "to": f"{end_epoch}000",
                        "query": f"service:{service} env:{env} resource_name:\"{resource}\" operation_name:servlet.request"
                    },
                    "page": {
                        "limit": 5000  # Elevated threshold to capture large historical window volume at once
                    }
                }
            }
        }
        
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=25)
            
            if response.status_code != 200:
                print(f"\n[DATADOG API REJECTION] HTTP status {response.status_code} for resource: {resource}")
                print(f"Details: {response.text}")
                return None
                
            span_events = response.json().get("data", [])
            total_requests = len(span_events)
            
            # If no traces match the window filters, gracefully return an empty metric record
            if total_requests == 0:
                return EndpointMetricsDTO(
                    service=service, resource=resource,
                    total_requests=0, total_errors_5xx=0, total_errors_4xx=0,
                    avg_latency=0.0, p95_latency=0.0, p99_latency=0.0
                )
                
            total_errors_5xx = 0
            total_errors_4xx = 0
            latency_sum = 0.0
            latencies = []

            for item in span_events:
                span_attrs = item.get("attributes", {})
                custom_tags = span_attrs.get("attributes", {})
                
                status = span_attrs.get("status", "success")
                http_status = custom_tags.get("http.status_code")
                
                if status == "error" or (http_status and str(http_status).startswith('5')):
                    total_errors_5xx += 1
                elif http_status and str(http_status).startswith('4'):
                    total_errors_4xx += 1
                
                # Convert nanoseconds to milliseconds
                duration_ns = span_attrs.get("duration", 0)
                duration_ms = float(duration_ns) / 1000000.0
                if duration_ms > 0:
                    latency_sum += duration_ms
                    latencies.append(duration_ms)

            latencies.sort()
            avg_latency = (latency_sum / len(latencies)) if latencies else 0.0
            
            p95_latency = 0.0
            p99_latency = 0.0
            if latencies:
                p95_idx = int(len(latencies) * 0.95)
                p99_idx = int(len(latencies) * 0.99)
                p95_latency = latencies[min(p95_idx, len(latencies) - 1)]
                p99_latency = latencies[min(p99_idx, len(latencies) - 1)]

            return EndpointMetricsDTO(
                service=service, resource=resource,
                total_requests=total_requests, total_errors_5xx=total_errors_5xx, total_errors_4xx=total_errors_4xx,
                avg_latency=avg_latency, p95_latency=p95_latency, p99_latency=p99_latency
            )
        except Exception as err:
            print(f"\n[LOCAL SCRIPT EXCEPTION] Parsing Error: {str(err)}")
            return None

    def get_endpoint_telemetry_parallel(self, env: str, service: str, resource: str, 
                                        start_epoch: int, end_epoch: int, metric_root: str = "trace.express.request") -> Optional[EndpointMetricsDTO]:
        if "servlet" in metric_root:
            return self._fetch_java_trace_analytics(env, service, resource, start_epoch, end_epoch)
            
        filter_tags = f"env:{env},resource:{resource},service:{service}"
        time_window_sec = end_epoch - start_epoch
        
        query_map = {
            "hits": f"sum:{metric_root}.hits{{{filter_tags}}}.as_count()",
            "errors_5xx": f"sum:{metric_root}.errors{{{filter_tags}}}.as_count()",
            "errors_4xx": f"sum:{metric_root}.hits{{{filter_tags},http.status_code:4*}}.as_count()",
            "avg": f"avg:{metric_root}{{{filter_tags}}}.as_rate().rollup(avg, {time_window_sec})",
            "p95": f"p95:{metric_root}{{{filter_tags}}}.as_rate().rollup(avg, {time_window_sec})",
            "p99": f"p99:{metric_root}{{{filter_tags}}}.as_rate().rollup(avg, {time_window_sec})"
        }
        
        raw_results = {}
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_to_metric = {
                executor.submit(self._execute_single_query, q_string, start_epoch, end_epoch): m_key 
                for m_key, q_string in query_map.items()
            }
            for future in as_completed(future_to_metric):
                metric_key = future_to_metric[future]
                payload = future.result()
                if payload:
                    raw_results[metric_key] = payload

        return self._parse_parallel_payloads(raw_results, service, resource)

    def get_bulk_telemetry(self, env: str, targets: List[Dict[str, str]], 
                           start_epoch: int, end_epoch: int, max_endpoints_at_once: int = 5) -> List[EndpointMetricsDTO]:
        bulk_results = []
        with ThreadPoolExecutor(max_workers=max_endpoints_at_once) as batch_executor:
            future_to_endpoint = {
                batch_executor.submit(
                    self.get_endpoint_telemetry_parallel, env, t["service"], t["resource"], start_epoch, end_epoch, t.get("metric_root", "trace.express.request")
                ): t for t in targets
            }
            for future in as_completed(future_to_endpoint):
                try:
                    dto = future.result()
                    if dto:
                        bulk_results.append(dto)
                except Exception:
                    pass
                    
        return bulk_results

    def _parse_parallel_payloads(self, results_map: Dict[str, Any], service: str, resource: str) -> Optional[EndpointMetricsDTO]:
        if not results_map:
            return None

        total_requests = self._extract_value(results_map.get("hits"), mode="sum")
        total_errors_5xx = self._extract_value(results_map.get("errors_5xx"), mode="sum")
        total_errors_4xx = self._extract_value(results_map.get("errors_4xx"), mode="sum")
        
        raw_avg = self._extract_value(results_map.get("avg"), mode="last") * 1000.0
        raw_p95 = self._extract_value(results_map.get("p95"), mode="last") * 1000.0
        raw_p99 = self._extract_value(results_map.get("p99"), mode="last") * 1000.0

        if raw_avg > 1000.0:
            raw_avg /= 1000.0; raw_p95 /= 1000.0; raw_p99 /= 1000.0

        return EndpointMetricsDTO(
            service=service, resource=resource,
            total_requests=int(total_requests), total_errors_5xx=int(total_errors_5xx), total_errors_4xx=int(total_errors_4xx),
            avg_latency=raw_avg, p95_latency=raw_p95, p99_latency=raw_p99
        )

    def _extract_value(self, payload: Optional[Dict[str, Any]], mode: str) -> float:
        if not payload or "series" not in payload or not payload["series"]:
            return 0.0
        pointlist = payload["series"][0].get("pointlist", [])
        valid_values = [p[1] for p in pointlist if p[1] is not None]
        if not valid_values:
            return 0.0
        return sum(valid_values) if mode == "sum" else valid_values[-1]