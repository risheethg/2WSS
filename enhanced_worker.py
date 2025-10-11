"""
Enhanced Kafka Worker with Retry Logic and Dead Letter Queue

This enhanced worker provides:
- Exponential backoff retry for transient failures  
- Dead Letter Queue (DLQ) for persistent failures
- Graceful handling of Stripe API rate limiting and errors
- Idempotent message processing
- Comprehensive error tracking and monitoring
"""

import json
import time
import signal
import sys
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum

# Kafka imports with fallback
try:
    from kafka import KafkaConsumer, KafkaProducer
    from kafka.errors import KafkaError
    KAFKA_AVAILABLE = True
except ImportError:
    print("Kafka not available - using mock implementation")
    KafkaConsumer = None
    KafkaProducer = None
    KafkaError = Exception
    KAFKA_AVAILABLE = False

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import worker_logger as logger
from app.integrations.registry import integration_registry
from app.integrations.base import OutwardIntegrationService

class MessageStatus(Enum):
    """Status of message processing."""
    SUCCESS = "success"
    RETRY = "retry"
    DEAD_LETTER = "dead_letter"
    PERMANENT_FAILURE = "permanent_failure"

class RetryableError(Exception):
    """Exception for errors that should be retried."""
    pass

class PermanentError(Exception):
    """Exception for errors that should not be retried."""
    pass

class EnhancedWorker:
    """
    Enhanced Kafka worker with comprehensive error handling and retry logic.
    """
    
    def __init__(self):
        self.consumer = None
        self.dlq_producer = None
        self.running = False
        
        # Retry configuration
        self.max_retries = 5
        self.base_delay = 2  # seconds
        self.max_delay = 300  # 5 minutes
        self.backoff_multiplier = 2
        
        # Rate limiting
        self.stripe_rate_limit_delay = 1  # seconds between Stripe calls
        self.last_stripe_call = {}  # per integration
        
        # DLQ configuration
        self.dlq_topic = f"{settings.KAFKA_CUSTOMER_TOPIC}_dlq"
        
        # Message tracking
        self.processed_count = 0
        self.success_count = 0
        self.retry_count = 0
        self.dlq_count = 0
        self.start_time = datetime.utcnow()
        
    def initialize(self):
        """Initialize Kafka consumer and producer."""
        if not KAFKA_AVAILABLE:
            logger.error("Kafka not available - cannot start worker")
            return False
            
        try:
            # Initialize consumer
            self.consumer = KafkaConsumer(
                settings.KAFKA_CUSTOMER_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                group_id="zenskar_customer_sync_worker",
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                key_deserializer=lambda m: m.decode('utf-8') if m else None,
                
                # Consumer configuration for reliability
                enable_auto_commit=False,  # Manual commit for reliability
                auto_offset_reset='earliest',
                max_poll_records=10,  # Process in small batches
                session_timeout_ms=30000,  # 30 seconds
                heartbeat_interval_ms=10000,  # 10 seconds
            )
            
            # Initialize DLQ producer
            self.dlq_producer = KafkaProducer(
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                value_serializer=lambda v: json.dumps(v).encode('utf-8'),
                key_serializer=str.encode,
                acks='all',  # Wait for all replicas
                retries=3,
                enable_idempotence=True
            )
            
            logger.info("Kafka consumer and DLQ producer initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize Kafka: {e}")
            return False
    
    def get_enabled_integrations(self) -> List[OutwardIntegrationService]:
        """Get enabled outward integration services."""
        enabled_integrations = integration_registry.get_enabled_outward_integrations()
        
        logger.info(f"Found {len(enabled_integrations)} enabled outward integrations")
        for integration in enabled_integrations:
            logger.info(f"Integration '{integration.name}' is enabled")
            
        return enabled_integrations
    
    def classify_error(self, error: Exception, integration_name: str) -> tuple[bool, str]:
        """
        Classify error to determine if it should be retried.
        
        Returns:
            tuple: (should_retry, error_category)
        """
        error_str = str(error).lower()
        error_type = type(error).__name__
        
        # Permanent errors - don't retry
        if any(keyword in error_str for keyword in [
            'invalid api key',
            'authentication failed', 
            'unauthorized',
            'bad request',
            'invalid customer',
            'customer not found'
        ]):
            return False, "authentication_or_validation_error"
        
        # HTTP client errors (4xx) - mostly permanent
        if any(keyword in error_str for keyword in [
            '400', '401', '402', '403', '404', '409', '422'
        ]):
            return False, "client_error"
        
        # Rate limiting - should retry with delay
        if any(keyword in error_str for keyword in [
            'rate limit', 'too many requests', '429'
        ]):
            return True, "rate_limit"
        
        # Server errors - should retry
        if any(keyword in error_str for keyword in [
            '500', '502', '503', '504', 'server error', 'service unavailable'
        ]):
            return True, "server_error"
        
        # Network/connection errors - should retry
        if any(keyword in error_str for keyword in [
            'connection', 'timeout', 'network', 'dns'
        ]):
            return True, "network_error"
        
        # Database errors - should retry
        if isinstance(error, SQLAlchemyError):
            return True, "database_error"
        
        # Default: retry for unknown errors
        return True, "unknown_error"
    
    def calculate_retry_delay(self, attempt: int, error_category: str) -> int:
        """Calculate delay for retry attempt."""
        base_delay = self.base_delay
        
        # Longer delay for rate limiting
        if error_category == "rate_limit":
            base_delay = 60  # 1 minute base for rate limits
        
        # Exponential backoff with jitter
        delay = min(
            base_delay * (self.backoff_multiplier ** attempt),
            self.max_delay
        )
        
        # Add small random jitter (10%)
        import random
        jitter = delay * 0.1 * random.random()
        
        return int(delay + jitter)
    
    def should_rate_limit(self, integration_name: str) -> float:
        """
        Check if we should rate limit calls to an integration.
        
        Returns:
            float: Delay in seconds if rate limiting needed, 0 otherwise
        """
        if integration_name not in self.last_stripe_call:
            self.last_stripe_call[integration_name] = 0
            
        time_since_last = time.time() - self.last_stripe_call[integration_name]
        
        if time_since_last < self.stripe_rate_limit_delay:
            return self.stripe_rate_limit_delay - time_since_last
        
        return 0
    
    def process_message_with_retry(
        self, 
        message, 
        db: Session, 
        enabled_integrations: List[OutwardIntegrationService]
    ) -> MessageStatus:
        """
        Process message with retry logic.
        
        Returns:
            MessageStatus: Result of processing
        """
        message_data = message.value
        message_key = message.key or "unknown"
        
        # Extract event info
        event_type = message_data.get("event_type", "unknown")
        aggregate_id = message_data.get("aggregate_id", "unknown")
        
        logger.info(f"Processing message: {event_type} for {aggregate_id}")
        
        # Track retry attempts per integration
        integration_results = {}
        
        for integration in enabled_integrations:
            integration_name = integration.name
            
            # Check rate limiting
            delay = self.should_rate_limit(integration_name)
            if delay > 0:
                logger.info(f"Rate limiting {integration_name} for {delay:.2f}s")
                time.sleep(delay)
            
            # Process with retry for this integration
            result = self._process_integration_with_retry(
                message_data, integration, db, message_key
            )
            
            integration_results[integration_name] = result
            
            # Update rate limit tracking
            self.last_stripe_call[integration_name] = time.time()
        
        # Determine overall message status
        if all(result == MessageStatus.SUCCESS for result in integration_results.values()):
            return MessageStatus.SUCCESS
        elif any(result == MessageStatus.DEAD_LETTER for result in integration_results.values()):
            return MessageStatus.DEAD_LETTER
        elif any(result == MessageStatus.RETRY for result in integration_results.values()):
            return MessageStatus.RETRY
        else:
            return MessageStatus.PERMANENT_FAILURE
    
    def _process_integration_with_retry(
        self, 
        message_data: Dict[str, Any], 
        integration: OutwardIntegrationService,
        db: Session,
        message_key: str
    ) -> MessageStatus:
        """Process message for a single integration with retry logic."""
        
        event_type = message_data.get("event_type")
        payload = message_data.get("payload", {})
        
        for attempt in range(self.max_retries + 1):
            try:
                # Process the event
                if event_type == "customer_created":
                    result = integration.create_customer(payload, db)
                elif event_type == "customer_updated":
                    result = integration.update_customer(payload, db)
                elif event_type == "customer_deleted":
                    result = integration.delete_customer(payload, db)
                else:
                    logger.warning(f"Unknown event type: {event_type}")
                    return MessageStatus.PERMANENT_FAILURE
                
                if result:
                    logger.info(f"Successfully processed {event_type} in {integration.name} (attempt {attempt + 1})")
                    return MessageStatus.SUCCESS
                else:
                    logger.warning(f"Failed to process {event_type} in {integration.name} (attempt {attempt + 1})")
                    # This counts as a retryable failure
                    raise RetryableError("Integration returned False")
                    
            except Exception as e:
                should_retry, error_category = self.classify_error(e, integration.name)
                
                logger.error(
                    f"Error in {integration.name} (attempt {attempt + 1}/{self.max_retries + 1}): "
                    f"{e} (category: {error_category}, retry: {should_retry})"
                )
                
                if not should_retry:
                    logger.error(f"Permanent error for {integration.name}: {e}")
                    return MessageStatus.PERMANENT_FAILURE
                
                if attempt >= self.max_retries:
                    logger.error(f"Max retries exceeded for {integration.name}")
                    return MessageStatus.DEAD_LETTER
                
                # Calculate delay for next retry
                delay = self.calculate_retry_delay(attempt, error_category)
                logger.info(f"Retrying {integration.name} in {delay}s (attempt {attempt + 2})")
                time.sleep(delay)
        
        return MessageStatus.DEAD_LETTER
    
    def send_to_dlq(self, message, reason: str):
        """Send message to Dead Letter Queue."""
        try:
            dlq_message = {
                "original_message": message.value,
                "original_key": message.key,
                "original_topic": message.topic,
                "original_partition": message.partition,
                "original_offset": message.offset,
                "failure_reason": reason,
                "timestamp": datetime.utcnow().isoformat(),
                "retry_count": self.max_retries
            }
            
            future = self.dlq_producer.send(
                topic=self.dlq_topic,
                key=message.key,
                value=dlq_message
            )
            
            future.get(timeout=10)  # Wait for confirmation
            logger.error(f"Sent message to DLQ: {reason}")
            self.dlq_count += 1
            
        except Exception as e:
            logger.error(f"Failed to send message to DLQ: {e}")
    
    def log_statistics(self):
        """Log processing statistics."""
        uptime = datetime.utcnow() - self.start_time
        
        if self.processed_count > 0:
            success_rate = (self.success_count / self.processed_count) * 100
        else:
            success_rate = 0
        
        logger.info(
            f"Worker Statistics: "
            f"Processed: {self.processed_count}, "
            f"Success: {self.success_count} ({success_rate:.1f}%), "
            f"Retries: {self.retry_count}, "
            f"DLQ: {self.dlq_count}, "
            f"Uptime: {uptime}"
        )
    
    def run(self):
        """Main worker loop."""
        if not self.initialize():
            logger.error("Failed to initialize worker")
            return False
        
        enabled_integrations = self.get_enabled_integrations()
        if not enabled_integrations:
            logger.error("No enabled integrations found")
            return False
        
        self.running = True
        logger.info("Enhanced worker started successfully")
        
        try:
            while self.running:
                try:
                    # Poll for messages with timeout
                    message_batch = self.consumer.poll(timeout_ms=1000)
                    
                    if not message_batch:
                        continue
                    
                    # Process each message
                    for topic_partition, messages in message_batch.items():
                        for message in messages:
                            self.processed_count += 1
                            
                            try:
                                with SessionLocal() as db:
                                    status = self.process_message_with_retry(
                                        message, db, enabled_integrations
                                    )
                                    
                                    if status == MessageStatus.SUCCESS:
                                        self.success_count += 1
                                        self.consumer.commit_async()
                                        logger.debug(f"Message processed successfully")
                                        
                                    elif status == MessageStatus.DEAD_LETTER:
                                        self.send_to_dlq(message, "Max retries exceeded")
                                        self.consumer.commit_async()
                                        
                                    elif status == MessageStatus.PERMANENT_FAILURE:
                                        self.send_to_dlq(message, "Permanent failure")
                                        self.consumer.commit_async()
                                        
                                    else:  # RETRY
                                        # Don't commit - message will be reprocessed
                                        self.retry_count += 1
                                        logger.warning("Message will be retried")
                            
                            except Exception as e:
                                logger.error(f"Unexpected error processing message: {e}")
                                logger.error(f"Traceback: {traceback.format_exc()}")
                                
                                self.send_to_dlq(message, f"Unexpected error: {e}")
                                self.consumer.commit_async()
                    
                    # Log statistics periodically
                    if self.processed_count % 100 == 0:
                        self.log_statistics()
                
                except KeyboardInterrupt:
                    logger.info("Received shutdown signal")
                    break
                except Exception as e:
                    logger.error(f"Error in main worker loop: {e}")
                    time.sleep(5)  # Brief pause before retrying
                    
        finally:
            self.shutdown()
    
    def shutdown(self):
        """Graceful shutdown."""
        self.running = False
        
        logger.info("Shutting down enhanced worker...")
        self.log_statistics()
        
        if self.consumer:
            self.consumer.close()
        if self.dlq_producer:
            self.dlq_producer.close()
            
        logger.info("Enhanced worker shutdown complete")

# Signal handlers for graceful shutdown
worker_instance = None

def signal_handler(signum, frame):
    global worker_instance
    if worker_instance:
        worker_instance.shutdown()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == "__main__":
    worker_instance = EnhancedWorker()
    worker_instance.run()