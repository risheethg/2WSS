"""
Outbox Event Processor

This module handles the reliable publishing of outbox events to Kafka.
It implements retry logic, exponential backoff, and dead letter queue handling.

Key features:
- Processes pending and retry-ready events
- Publishes to Kafka with partition key for ordering
- Handles transient failures with retry
- Moves persistently failed events to dead letter queue
"""

import json
import logging
import time
import asyncio
from typing import Dict, Any, Optional, List, Union
from datetime import datetime

logger = logging.getLogger(__name__)

# Kafka imports with fallback handling
try:
    from kafka import KafkaProducer
    from kafka.errors import KafkaError, KafkaTimeoutError, RetriableError
    KAFKA_AVAILABLE = True
except ImportError:
    logger.warning("Kafka not available, using mock implementation")
    # Create mock classes for development
    class MockKafkaProducer:
        def __init__(self, **kwargs): pass
        def send(self, **kwargs): 
            class MockFuture:
                def get(self, timeout=None):
                    class MockMetadata:
                        def __init__(self):
                            self.topic = "mock"
                            self.partition = 0
                            self.offset = 0
                    return MockMetadata()
            return MockFuture()
        def close(self): pass
    
    KafkaProducer = MockKafkaProducer
    KafkaError = Exception
    KafkaTimeoutError = Exception  
    RetriableError = Exception
    KAFKA_AVAILABLE = False

from app.core.database import get_db_session
from app.services.outbox_service import outbox_service
from app.models.outbox import OutboxEvent, EventStatus
from app.core.config import settings

class OutboxProcessor:
    """
    Processes outbox events and publishes them to Kafka reliably.
    """
    
    def __init__(self):
        self.producer = None
        self.processing = False
        self.batch_size = 50
        self.processing_interval = 5  # seconds
        
    def initialize_producer(self) -> Any:
        """Initialize Kafka producer with optimal settings."""
        try:
            producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                
                # Reliability settings
                acks='all',  # Wait for all replicas to acknowledge
                retries=5,   # Retry failed sends
                enable_idempotence=True,  # Prevent duplicate messages
                
                # Batching for performance
                batch_size=16384,  # 16KB batches
                linger_ms=10,      # Wait up to 10ms to fill batch
                
                # Serialization
                key_serializer=str.encode,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                
                # Timeouts
                request_timeout_ms=30000,  # 30 seconds
                delivery_timeout_ms=120000,  # 2 minutes total
                
                # Compression
                compression_type='snappy'
            )
            
            logger.info("Kafka producer initialized successfully")
            return producer
            
        except Exception as e:
            logger.error(f"Failed to initialize Kafka producer: {e}")
            raise
    
    def get_producer(self) -> Any:
        """Get or create Kafka producer."""
        if self.producer is None:
            self.producer = self.initialize_producer()
        return self.producer
    
    async def process_pending_events(self) -> Dict[str, int]:
        """
        Process all pending outbox events.
        
        Returns:
            Dict: Processing statistics
        """
        stats = {
            "processed": 0,
            "published": 0, 
            "failed": 0,
            "dead_letter": 0
        }
        
        with get_db_session() as db:
            # Get pending events
            pending_events = outbox_service.get_pending_events(db, limit=self.batch_size)
            
            # Get retry-ready events
            retry_events = outbox_service.get_retry_ready_events(db, limit=self.batch_size)
            
            # Combine and process
            all_events = pending_events + retry_events
            
            if not all_events:
                logger.debug("No events to process")
                return stats
            
            logger.info(f"Processing {len(all_events)} outbox events")
            
            for event in all_events:
                try:
                    # Mark as processing (with optimistic locking)
                    if not outbox_service.mark_processing(db, event):
                        continue  # Already being processed
                    
                    stats["processed"] += 1
                    
                    # Publish to Kafka
                    success = await self._publish_event(event)
                    
                    if success:
                        outbox_service.mark_published(db, event)
                        stats["published"] += 1
                        logger.debug(f"Successfully published event {event.id}")
                    else:
                        # Publishing failed, mark for retry or DLQ
                        error_msg = "Failed to publish to Kafka"
                        outbox_service.mark_failed(db, event, error_msg)
                        
                        if event.retry_count >= event.max_retries:
                            stats["dead_letter"] += 1
                        else:
                            stats["failed"] += 1
                
                except Exception as e:
                    logger.error(f"Error processing event {event.id}: {e}")
                    
                    # Mark as failed with error details
                    error_details = {
                        "error_type": type(e).__name__,
                        "error_message": str(e),
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    
                    outbox_service.mark_failed(db, event, str(e), error_details)
                    
                    if event.retry_count >= event.max_retries:
                        stats["dead_letter"] += 1
                    else:
                        stats["failed"] += 1
        
        logger.info(f"Outbox processing complete: {stats}")
        return stats
    
    async def _publish_event(self, event: OutboxEvent) -> bool:
        """
        Publish a single event to Kafka.
        
        Args:
            event: Outbox event to publish
            
        Returns:
            bool: True if published successfully, False otherwise
        """
        try:
            producer = self.get_producer()
            
            # Prepare message
            message_value = {
                "event_type": event.event_type,
                "aggregate_id": event.aggregate_id,
                "aggregate_type": event.aggregate_type,
                "payload": event.payload,
                "metadata": event.metadata or {},
                "event_id": str(event.id),
                "timestamp": event.created_at.isoformat(),
                "version": "1.0"
            }
            
            # Send to Kafka with partition key for ordering
            future = producer.send(
                topic=event.topic,
                key=event.partition_key,
                value=message_value,
                headers=[
                    ("event_type", event.event_type.encode()),
                    ("aggregate_type", event.aggregate_type.encode()),
                    ("event_id", str(event.id).encode())
                ]
            )
            
            # Wait for acknowledgment (with timeout)
            record_metadata = future.get(timeout=30)
            
            logger.debug(
                f"Event {event.id} published to {record_metadata.topic} "
                f"partition {record_metadata.partition} offset {record_metadata.offset}"
            )
            
            return True
            
        except KafkaTimeoutError as e:
            logger.warning(f"Kafka timeout publishing event {event.id}: {e}")
            return False
            
        except RetriableError as e:
            logger.warning(f"Retriable Kafka error for event {event.id}: {e}")
            return False
            
        except KafkaError as e:
            logger.error(f"Kafka error publishing event {event.id}: {e}")
            return False
            
        except Exception as e:
            logger.error(f"Unexpected error publishing event {event.id}: {e}")
            return False
    
    async def start_background_processor(self):
        """
        Start the background event processor.
        
        This runs continuously and processes outbox events at regular intervals.
        """
        if self.processing:
            logger.warning("Outbox processor already running")
            return
        
        self.processing = True
        logger.info("Starting outbox background processor")
        
        try:
            while self.processing:
                try:
                    # Process events
                    stats = await self.process_pending_events()
                    
                    # Log statistics if any events were processed
                    if stats["processed"] > 0:
                        logger.info(f"Outbox processor cycle: {stats}")
                    
                    # Wait before next cycle
                    await asyncio.sleep(self.processing_interval)
                    
                except Exception as e:
                    logger.error(f"Error in outbox processor cycle: {e}")
                    # Wait a bit longer after error
                    await asyncio.sleep(self.processing_interval * 2)
                    
        except asyncio.CancelledError:
            logger.info("Outbox processor cancelled")
        except Exception as e:
            logger.error(f"Outbox processor failed: {e}")
        finally:
            self.processing = False
            logger.info("Outbox processor stopped")
    
    def stop_background_processor(self):
        """Stop the background processor."""
        self.processing = False
        logger.info("Stopping outbox processor")
    
    def close(self):
        """Close Kafka producer and cleanup resources."""
        if self.producer:
            self.producer.close()
            self.producer = None
        self.stop_background_processor()
        logger.info("Outbox processor closed")
    
    async def process_dead_letter_queue(self, limit: int = 10) -> Dict[str, int]:
        """
        Process dead letter queue for manual recovery.
        
        Args:
            limit: Maximum number of DLQ events to process
            
        Returns:
            Dict: Recovery statistics
        """
        stats = {"recovered": 0, "still_failed": 0}
        
        with get_db_session() as db:
            dlq_events = outbox_service.get_dead_letter_events(db, limit=limit)
            
            for event in dlq_events:
                logger.info(f"Attempting to recover DLQ event {event.id}")
                
                # Reset for retry
                if outbox_service.retry_dead_letter_event(db, str(event.id)):
                    # Try to process immediately
                    success = await self._publish_event(event)
                    
                    if success:
                        outbox_service.mark_published(db, event)
                        stats["recovered"] += 1
                        logger.info(f"Successfully recovered DLQ event {event.id}")
                    else:
                        stats["still_failed"] += 1
                        outbox_service.mark_failed(db, event, "Manual recovery failed")
                
        logger.info(f"DLQ processing complete: {stats}")
        return stats

# Global processor instance  
outbox_processor = OutboxProcessor()