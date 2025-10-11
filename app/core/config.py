from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str

    KAFKA_BOOTSTRAP_SERVERS: str
    KAFKA_CUSTOMER_TOPIC: str
    KAFKA_DLQ_TOPIC: str = "customer_events_dlq"  # Dead Letter Queue

    STRIPE_API_KEY: str
    STRIPE_WEBHOOK_SECRET: str

    LOGGER: str
    
    # Integration configuration
    ENABLED_INTEGRATIONS: str = "stripe"  # Comma-separated list of enabled integrations
    STRIPE_INTEGRATION_ENABLED: bool = True
    SALESFORCE_INTEGRATION_ENABLED: bool = False
    
    # Retry configuration
    MAX_RETRY_ATTEMPTS: int = 5
    INITIAL_RETRY_DELAY: int = 2  # seconds
    MAX_RETRY_DELAY: int = 300    # seconds (5 minutes)
    
    # Conflict resolution configuration
    CONFLICT_RESOLUTION_STRATEGY: str = "flag"  # flag, reject, merge, auto_rename
    AUTO_RESOLVE_CONFLICTS: bool = False        # Whether to auto-resolve simple conflicts
    
    # Reconciliation configuration
    RECONCILIATION_HOUR: int = 2        # Hour to run reconciliation (24-hour format)
    RECONCILIATION_MINUTE: int = 0      # Minute to run reconciliation
    RECONCILIATION_AUTO_RESOLVE: bool = True  # Auto-resolve simple mismatches during scheduled runs
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')
    
    def get_enabled_integrations(self) -> List[str]:
        """Get enabled integration names from config."""
        if not self.ENABLED_INTEGRATIONS:
            return []
        return [name.strip().lower() for name in self.ENABLED_INTEGRATIONS.split(",") if name.strip()]

settings = Settings()

def get_settings() -> Settings:
    """Get application settings."""
    return settings