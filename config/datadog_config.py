import os
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

class DatadogConfigProperties:
    """
    Acts like Spring Boot's @ConfigurationProperties.
    Loads environment variables from the parent directory's .env file dynamically.
    """
    def __init__(self):
        current_file_path = Path(__file__).resolve()
        parent_directory = current_file_path.parent.parent
        env_path = parent_directory / '.env'
        
        load_dotenv(dotenv_path=env_path)
        
        self.api_key: str = os.getenv("DD_API_KEY") or os.getenv("DATADOG_API_KEY") or ""
        self.app_key: str = os.getenv("DD_APP_KEY") or os.getenv("DATADOG_APP_KEY") or ""
        self.site: str = os.getenv("DD_SITE") or "datadoghq.com"

    def _get_base_domain(self) -> str:
        """Helper to cleanly extract the right regional API endpoint domain."""
        clean_site = self.site.strip()
        if clean_site.startswith("api."):
            return clean_site
        return f"api.{clean_site}"

    def get_v1_query_url(self) -> str:
        return f"https://{self._get_base_domain()}/api/v1/query"
    
    def get_v2_spans_url(self) -> str:
        # FIXED: Now dynamically targets your exact corporate Datadog cloud region!
        return f"https://{self._get_base_domain()}/api/v2/spans/events/search"

    def get_standard_headers(self) -> Dict[str, str]:
        # FIXED: Explicitly added Content-Type so Datadog maps the incoming POST layout
        return {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "DD-API-KEY": self.api_key,
            "DD-APPLICATION-KEY": self.app_key
        }