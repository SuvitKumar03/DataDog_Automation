class EndpointMetricsDTO:
    """
    Domain Data Model representing structured runtime profile states.
    Enhanced to carry target context for multi-service parallel mapping.
    """
    def __init__(self, service: str, resource: str, total_requests: int = 0, 
                 total_errors_5xx: int = 0, total_errors_4xx: int = 0,
                 avg_latency: float = 0.0, p95_latency: float = 0.0, p99_latency: float = 0.0):
        self.service = service
        self.resource = resource
        self.total_requests = total_requests
        self.total_errors_5xx = total_errors_5xx
        self.total_errors_4xx = total_errors_4xx
        self.avg_latency = avg_latency
        self.p95_latency = p95_latency
        self.p99_latency = p99_latency

    @property
    def server_error_rate_5xx(self) -> float:
        if self.total_requests > 0:
            return (self.total_errors_5xx * 100.0) / self.total_requests
        return 0.0

    @property
    def client_error_rate_4xx(self) -> float:
        if self.total_requests > 0:
            return (self.total_errors_4xx * 100.0) / self.total_requests
        return 0.0