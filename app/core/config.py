from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List

class Settings(BaseSettings):
    DATABASE_URL: str

    KAFKA_BOOTSTRAP_SERVERS: str
    KAFKA_CUSTOMER_TOPIC: str

    STRIPE_API_KEY: str
    STRIPE_WEBHOOK_SECRET: str

    LOGGER: str
    
    # Integration configuration
    ENABLED_INTEGRATIONS: str = "stripe"  # Comma-separated list of enabled integrations
    STRIPE_INTEGRATION_ENABLED: bool = True
    SALESFORCE_INTEGRATION_ENABLED: bool = False
    
    # Database connection pool configuration
    DB_POOL_SIZE: int = 20  # Maximum number of persistent connections
    DB_MAX_OVERFLOW: int = 30  # Additional connections beyond pool_size
    DB_POOL_TIMEOUT: int = 30  # Seconds to wait for connection
    DB_POOL_RECYCLE: int = 3600  # Seconds before connection refresh (1 hour)
    DB_POOL_PRE_PING: bool = True  # Test connections before use
    DB_CONNECT_TIMEOUT: int = 10  # Connection establishment timeout
    DB_COMMAND_TIMEOUT: int = 300  # SQL command execution timeout (5 minutes)
    
    # Transaction and retry configuration
    DB_MAX_RETRIES: int = 3  # Max retries for database operations
    DB_RETRY_BASE_DELAY: float = 0.1  # Base delay for exponential backoff
    DB_RETRY_MAX_DELAY: float = 5.0  # Maximum delay between retries
    DB_DEADLOCK_RETRY_COUNT: int = 5  # Specific retries for deadlocks
    
    # Session configuration
    DB_SESSION_TIMEOUT: int = 1800  # Session timeout in seconds (30 minutes)
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')
    
    def get_enabled_integrations(self) -> List[str]:
        """Get enabled integration names from config."""
        if not self.ENABLED_INTEGRATIONS:
            return []
        return [name.strip().lower() for name in self.ENABLED_INTEGRATIONS.split(",") if name.strip()]

settings = Settings()