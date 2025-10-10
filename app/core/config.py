from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    DATABASE_URL: str

    KAFKA_BOOTSTRAP_SERVERS: str
    KAFKA_CUSTOMER_TOPIC: str

    STRIPE_API_KEY: str
    STRIPE_WEBHOOK_SECRET: str

    LOGGER: str
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')

settings = Settings()