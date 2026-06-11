import time
import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="urllib3")

from config.datadog_config import DatadogConfigProperties
from service.datadog_service import DatadogMetricsService

def run_application():
    print("\n======================================================================")
    print("STARTING CONTROLLED TARGET RUN: CLISOMW + B2B LEDGER ISOLATION TEST")
    print("======================================================================")
    
    config_props = DatadogConfigProperties()
    metrics_service = DatadogMetricsService(config_props)
    
    # ------------------------------------------------------------------
    # TIMEFRAME: Matching your active June 1 - June 7, 2026 URL perfectly
    # ------------------------------------------------------------------
    START_EPOCH = 1780252200
    END_EPOCH = 1780857000
    ENV = "none"
    
    # Cleaned registry: Just clisomw and the single targeted B2B Ledger route
    target_registry = [
        {
            "service": "prod-clisomw-deployment", 
            "resource": "5e52f68a12aff7d2",
            "metric_root": "trace.express.request"
        },
        {
            "service": "production-b2b-ledger-service-deployment", 
            "resource": "POST /ledger/api/v1/ledgerDetail",
            "metric_root": "trace.servlet.request"
        }
    ]
    
    execution_start_time = time.time()
    
    # Fire execution matrix
    metrics_batch_output = metrics_service.get_bulk_telemetry(
        env=ENV,
        targets=target_registry,
        start_epoch=START_EPOCH,
        end_epoch=END_EPOCH,
        max_endpoints_at_once=2
    )
    
    execution_end_time = time.time()
    elapsed_duration_seconds = execution_end_time - execution_start_time
    
    print(f"\nSuccessfully Compiled Metrics Matrix for {len(metrics_batch_output)} Live Targets:")
    print("======================================================================")
    
    for dto in metrics_batch_output:
        print(f"SERVICE:  [{dto.service}]")
        print(f"RESOURCE: [{dto.resource}]")
        print(f" -> Volume: {dto.total_requests} counts")
        print(f" -> 5xx Server Errors: {dto.total_errors_5xx} counts ({round(dto.server_error_rate_5xx, 2)}%)")
        print(f" -> 4xx Client Errors: {dto.total_errors_4xx} counts ({round(dto.client_error_rate_4xx, 2)}%)")
        print(f" -> Latency profile: Avg: {round(dto.avg_latency, 1)}ms | p95: {round(dto.p95_latency, 1)}ms | p99: {round(dto.p99_latency, 1)}ms")
        print("----------------------------------------------------------------------")
        
    print(f"TOTAL SYSTEM BATCH PERFORMANCE: Executed in {round(elapsed_duration_seconds, 3)} seconds")
    print("======================================================================")

if __name__ == "__main__":
    run_application()