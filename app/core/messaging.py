import json
from kafka import KafkaProducer
from sqlalchemy.orm import Session
from typing import Optional
from .config import settings
from .logger import logger


class KafkaPublisher:
    """Kafka producer wrapper with partition key support"""
    
    def __init__(self):
        self._producer = None
    
    @property
    def producer(self):
        """Lazy initialization of Kafka producer"""
        if self._producer is None:
            self._producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                key_serializer=lambda k: str(k).encode('utf-8') if k else None
            )
        return self._producer
    
    def send_event(self, topic: str, event_data: dict, partition_key: str = None):
        """Send event to Kafka with optional partition key for ordering"""
        try:
            self.producer.send(
                topic=topic,
                value=event_data,
                key=partition_key  # Ensures ordering for events with same key
            )
            self.producer.flush()
            logger.info(f"Published event to Kafka: {event_data.get('event_type')} with key: {partition_key}")
            return True
        except Exception as e:
            logger.error(f"Failed to publish event to Kafka: {e}")
            return False


# Global publisher instance
kafka_publisher = KafkaPublisher()


def send_customer_event(event_type: str, customer_data: dict):
    """
    Legacy function - sends customer event directly to Kafka.
    
    Note: This bypasses the outbox pattern. Use add_event_to_outbox() for
    transactional safety in production scenarios.
    """
    message = {
        "event_type": event_type,
        "customer": customer_data
    }
    
    # Use customer ID as partition key for ordering
    partition_key = str(customer_data.get('id', '')) if customer_data.get('id') else None
    
    success = kafka_publisher.send_event(settings.KAFKA_CUSTOMER_TOPIC, message, partition_key)
    if success:
        logger.info(f"Sent event '{event_type}' for customer ID {customer_data.get('id')}")
    else:
        logger.error(f"Failed to send event '{event_type}' for customer ID {customer_data.get('id')}")


def add_event_to_outbox(db: Session, event_type: str, entity_type: str, entity_data: dict):
    """
    Add event to outbox table within the same transaction.
    
    This implements the Transactional Outbox Pattern - events are only
    added to the outbox if the main database transaction succeeds.
    """
    from app.repos.outbox_repo import outbox_repo
    from app.models.outbox import OutboxEventCreate
    
    entity_id = str(entity_data.get('id', ''))
    
    event_data = OutboxEventCreate(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload={
            "event_type": event_type,
            entity_type: entity_data
        }
    )
    
    try:
        outbox_event = outbox_repo.create_event(db, event_data)
        logger.info(f"Added {event_type} event to outbox for {entity_type} ID {entity_id}")
        return outbox_event
    except Exception as e:
        logger.error(f"Failed to add event to outbox: {e}")
        raise