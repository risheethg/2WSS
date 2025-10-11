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
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')
    
    def get_enabled_integrations(self) -> List[str]:
        """Get enabled integration names from config."""
        if not self.ENABLED_INTEGRATIONS:
            return []
        return [name.strip().lower() for name in self.ENABLED_INTEGRATIONS.split(",") if name.strip()]

settings = Settings()