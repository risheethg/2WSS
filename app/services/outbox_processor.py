"""
Outbox Processor Service

Background service that reads from the outbox table and publishes events to Kafka.
This completes the Transactional Outbox Pattern implementation.
"""

import time
import threading
from typing import List
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import worker_logger as logger
from app.core.messaging import kafka_publisher
from app.repos.outbox_repo import outbox_repo
from app.models.outbox import OutboxEventInDB


class OutboxProcessor:
    """Processes outbox events and publishes them to Kafka"""
    
    def __init__(self, batch_size: int = 50, poll_interval: int = 5):
        self.batch_size = batch_size
        self.poll_interval = poll_interval  # seconds
        self.running = False
        self.thread = None

    def start(self):
        """Start the outbox processor in a background thread"""
        if self.running:
            logger.warning("Outbox processor is already running")
            return
            
        self.running = True
        self.thread = threading.Thread(target=self._process_loop, daemon=True)
        self.thread.start()
        logger.info("Outbox processor started")

    def stop(self):
        """Stop the outbox processor"""
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=10)
        logger.info("Outbox processor stopped")

    def _process_loop(self):
        """Main processing loop"""
        while self.running:
            try:
                db = SessionLocal()
                try:
                    processed_count = self._process_batch(db)
                    if processed_count > 0:
                        logger.info(f"Processed {processed_count} outbox events")
                finally:
                    db.close()
                    
            except Exception as e:
                logger.error(f"Error in outbox processor loop: {e}")
                
            time.sleep(self.poll_interval)

    def _process_batch(self, db: Session) -> int:
        """Process a batch of outbox events"""
        try:
            # Get unprocessed events
            events = outbox_repo.get_unprocessed_events(db, limit=self.batch_size)
            
            if not events:
                return 0
                
            processed_count = 0
            
            for event in events:
                try:
                    success = self._publish_event(event)
                    
                    if success:
                        # Mark as processed
                        outbox_repo.mark_as_processed(db, event.id)
                        processed_count += 1
                        logger.debug(f"Published outbox event {event.id}: {event.event_type}")
                    else:
                        # Increment retry count
                        outbox_repo.increment_retry_count(
                            db, 
                            event.id, 
                            "Failed to publish to Kafka"
                        )
                        logger.warning(f"Failed to publish outbox event {event.id}")
                        
                except Exception as e:
                    # Increment retry count with error message
                    outbox_repo.increment_retry_count(
                        db, 
                        event.id, 
                        str(e)
                    )
                    logger.error(f"Error processing outbox event {event.id}: {e}")
                    
            return processed_count
            
        except Exception as e:
            logger.error(f"Error processing outbox batch: {e}")
            return 0

    def _publish_event(self, event: OutboxEventInDB) -> bool:
        """Publish a single outbox event to Kafka"""
        try:
            payload = event.get_payload()
            
            # Determine the appropriate Kafka topic based on entity type
            topic = self._get_topic_for_entity(event.entity_type)
            
            # Use entity_id as partition key for ordering
            partition_key = event.entity_id
            
            success = kafka_publisher.send_event(
                topic=topic,
                event_data=payload,
                partition_key=partition_key
            )
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to publish outbox event {event.id}: {e}")
            return False

    def _get_topic_for_entity(self, entity_type: str) -> str:
        """Map entity type to Kafka topic"""
        topic_mapping = {
            "customer": settings.KAFKA_CUSTOMER_TOPIC,
            # Add more mappings as needed:
            # "invoice": settings.KAFKA_INVOICE_TOPIC,
            # "product": settings.KAFKA_PRODUCT_TOPIC,
        }
        
        return topic_mapping.get(entity_type, settings.KAFKA_CUSTOMER_TOPIC)

    def process_failed_events(self, db: Session) -> int:
        """Process events that have exceeded retry limits - send to DLQ"""
        try:
            failed_events = outbox_repo.get_failed_events(db, max_retries=settings.MAX_RETRY_ATTEMPTS)
            
            dlq_count = 0
            for event in failed_events:
                try:
                    # Send to dead letter queue
                    dlq_message = {
                        "outbox_event_id": event.id,
                        "event_type": event.event_type,
                        "entity_type": event.entity_type,
                        "entity_id": event.entity_id,
                        "payload": event.get_payload(),
                        "retry_count": event.retry_count,
                        "last_error": event.last_error,
                        "failed_at": time.time()
                    }
                    
                    success = kafka_publisher.send_event(
                        topic=settings.KAFKA_DLQ_TOPIC,
                        event_data=dlq_message,
                        partition_key=event.entity_id
                    )
                    
                    if success:
                        # Mark as processed (failed)
                        outbox_repo.mark_as_processed(db, event.id)
                        dlq_count += 1
                        logger.warning(f"Sent failed outbox event {event.id} to DLQ after {event.retry_count} retries")
                        
                except Exception as e:
                    logger.error(f"Error sending failed event {event.id} to DLQ: {e}")
                    
            return dlq_count
            
        except Exception as e:
            logger.error(f"Error processing failed outbox events: {e}")
            return 0

    def cleanup_old_events(self, db: Session, days_old: int = 30) -> int:
        """Clean up old processed events"""
        try:
            deleted_count = outbox_repo.delete_old_processed_events(db, days_old)
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old outbox events")
            return deleted_count
        except Exception as e:
            logger.error(f"Error cleaning up old outbox events: {e}")
            return 0


# Global outbox processor instance
outbox_processor = OutboxProcessor()