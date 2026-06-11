# exceptions/pipeline_exceptions.py

class ThyrocarePipelineError(Exception):
    """Base exception for all errors inside the Thyrocare Automation pipeline."""
    def __init__(self, message, error_code=None):
        super().__init__(message)
        self.message = message
        self.error_code = error_code

class GoogleSheetsConnectionError(ThyrocarePipelineError):
    """Raised when the script fails to authenticate, access, or write to Google Sheets."""
    pass

class DatadogFetchError(ThyrocarePipelineError):
    """Raised when pulling metrics from the Datadog API fails."""
    pass