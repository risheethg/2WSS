import json
import time
from kafka import KafkaConsumer
from kafka.errors import KafkaError
from sqlalchemy.orm import Session
from typing import List

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import worker_logger as logger
from app.core.retry import event_processor, NonRetryableError
from app.core.messaging import kafka_publisher
from app.integrations.registry import integration_registry
from app.integrations.base import OutwardIntegrationService
from app.services.outbox_processor import outbox_processor

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

def send_to_dead_letter_queue(message, error_reason: str):
    """Send failed message to Dead Letter Queue"""
    try:
        dlq_message = {
            "original_message": json.loads(message.value.decode('utf-8')),
            "error_reason": error_reason,
            "failed_at": time.time(),
            "topic": message.topic,
            "partition": message.partition,
            "offset": message.offset
        }
        
        # Use customer ID as partition key for DLQ as well
        original_event = dlq_message["original_message"]
        customer_data = original_event.get("customer", {})
        partition_key = str(customer_data.get("id", "")) if customer_data.get("id") else None
        
        success = kafka_publisher.send_event(
            topic=settings.KAFKA_DLQ_TOPIC,
            event_data=dlq_message,
            partition_key=partition_key
        )
        
        if success:
            logger.error(f"Sent message to DLQ: {error_reason}")
        else:
            logger.error(f"Failed to send message to DLQ: {error_reason}")
            
    except Exception as dlq_error:
        logger.error(f"Critical error sending to DLQ: {dlq_error}")


def process_message(message, db: Session, enabled_integrations: List[OutwardIntegrationService]):
    """Process Kafka message with retry logic and dead letter queue handling."""
    try:
        event = json.loads(message.value)
        event_type = event.get("event_type")
        customer_data = event.get("customer")
        local_customer_id = customer_data.get("id")

        logger.info(f"Processing event: {event_type} for local customer ID: {local_customer_id}")
        logger.info(f"Dispatching to {len(enabled_integrations)} enabled integration(s)")

        # Process each integration with retry logic
        for integration in enabled_integrations:
            try:
                # Use the retry-enabled event processor
                result = event_processor.process_stripe_event(
                    integration=integration,
                    event_type=event_type,
                    customer_data=customer_data,
                    db=db
                )
                
                if result:
                    logger.info(f"Successfully processed {event_type} in {integration.name} integration")
                else:
                    logger.warning(f"Integration {integration.name} returned no result for {event_type}")
                        
            except NonRetryableError as non_retryable:
                # Don't retry, but log the error
                error_msg = f"Non-retryable error in {integration.name} for {event_type}: {non_retryable}"
                logger.error(error_msg)
                send_to_dead_letter_queue(message, error_msg)
                continue
                
            except Exception as integration_error:
                # After all retries are exhausted, send to DLQ
                error_msg = f"All retries exhausted for {integration.name} integration, event {event_type}: {integration_error}"
                logger.error(error_msg)
                send_to_dead_letter_queue(message, error_msg)
                continue
                
    except json.JSONDecodeError as json_error:
        error_msg = f"Invalid JSON in message: {json_error}"
        logger.error(error_msg)
        send_to_dead_letter_queue(message, error_msg)
    except Exception as e:
        error_msg = f"Unexpected error processing message: {e}"
        logger.error(error_msg)
        send_to_dead_letter_queue(message, error_msg)

def main():
    """Main worker loop - processes Kafka events and outbox publishing."""
    db: Session = None
    consumer: KafkaConsumer = None
    enabled_integrations: List[OutwardIntegrationService] = []

    # Start the outbox processor
    logger.info("Starting outbox processor...")
    outbox_processor.start()

    try:
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
                
    finally:
        # Cleanup on exit
        logger.info("Shutting down worker...")
        outbox_processor.stop()
        if consumer:
            consumer.close()
        if db:
            db.close()

if __name__ == "__main__":
    main()