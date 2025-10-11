import json
import time
from kafka import KafkaConsumer
from sqlalchemy.orm import Session
from typing import List

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import worker_logger as logger
from app.integrations.registry import integration_registry
from app.integrations.base import OutwardIntegrationService

logger.info("Integration Worker starting...")

def get_enabled_integrations() -> List[OutwardIntegrationService]:
    """Get enabled outward integration services."""
    enabled_integrations = integration_registry.get_enabled_outward_integrations()
    
    logger.info(f"Found {len(enabled_integrations)} enabled outward integrations")
    for integration in enabled_integrations:
        logger.info(f"Integration '{integration.name}' is enabled and will process events")
    
    return enabled_integrations

def get_db_session():
    """Get new DB session for worker."""
    return SessionLocal()

def process_message(message, db: Session, enabled_integrations: List[OutwardIntegrationService]):
    """Process Kafka message and dispatch to enabled integrations."""
    try:
        event = json.loads(message.value)
        event_type = event.get("event_type")
        customer_data = event.get("customer")
        local_customer_id = customer_data.get("id")

        logger.info(f"Processing event: {event_type} for local customer ID: {local_customer_id}")
        logger.info(f"Dispatching to {len(enabled_integrations)} enabled integration(s)")

        # Send event to all enabled integrations
        for integration in enabled_integrations:
            try:
                if event_type == "customer_created":
                    result = integration.create_customer(customer_data, db)
                    if result:
                        logger.info(f"Successfully processed {event_type} in {integration.name} integration")
                    else:
                        logger.warning(f"Failed to process {event_type} in {integration.name} integration")
                        
                elif event_type == "customer_updated":
                    result = integration.update_customer(customer_data, db)
                    if result:
                        logger.info(f"Successfully processed {event_type} in {integration.name} integration")
                    else:
                        logger.warning(f"Failed to process {event_type} in {integration.name} integration")
                        
                elif event_type == "customer_deleted":
                    result = integration.delete_customer(customer_data, db)
                    if result:
                        logger.info(f"Successfully processed {event_type} in {integration.name} integration")
                    else:
                        logger.warning(f"Failed to process {event_type} in {integration.name} integration")
                        
                else:
                    logger.warning(f"Unhandled event type: {event_type}")
                    
            except Exception as integration_error:
                logger.error(f"Error in {integration.name} integration for {event_type}: {integration_error}")
                # Continue with other integrations if one fails
                continue
                
    except Exception as e:
        logger.error(f"An unexpected error occurred processing message: {e}")

def main():
    """Main worker loop - processes Kafka events and dispatches to integrations."""
    db: Session = None
    consumer: KafkaConsumer = None
    enabled_integrations: List[OutwardIntegrationService] = []

    while True:
        try:
            # Ensure we have a valid DB session
            if not db or not db.is_active:
                if db:
                    db.close()
                db = get_db_session()
                logger.info("Database session established/re-established.")

            # Get enabled integrations
            enabled_integrations = get_enabled_integrations()
            
            if not enabled_integrations:
                logger.warning("No integrations are enabled. Worker will continue but no events will be processed.")

            # Setup Kafka consumer
            if not consumer:
                logger.info("Connecting to Kafka...")
                consumer = KafkaConsumer(
                    settings.KAFKA_CUSTOMER_TOPIC,
                    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                    auto_offset_reset='earliest',
                    group_id='integration-dispatcher-group',
                    request_timeout_ms=15000
                )
                logger.info("Successfully connected to Kafka. Listening for messages...")

            # This will block until a message is received
            for message in consumer:
                if enabled_integrations:
                    process_message(message, db, enabled_integrations)
                else:
                    logger.debug("Skipping message processing - no enabled integrations")

        except Exception as e:
            logger.error(f"An error occurred in the main worker loop: {e}")
            # Clean up resources before retrying
            if consumer:
                consumer.close()
                consumer = None
            if db:
                db.close()
                db = None
            
            logger.info("Retrying in 15 seconds...")
            time.sleep(15)

if __name__ == "__main__":
    main()