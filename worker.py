import json
import time
from kafka import KafkaConsumer
import stripe
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logger import worker_logger as logger
from app.models.customer import Customer

# Configure Stripe client
stripe.api_key = settings.STRIPE_API_KEY

logger.info("Worker starting...")

def get_db_session():
    """Helper to get a new DB session for the worker."""
    return SessionLocal()

def process_message(message, db: Session):
    """Processes a single message from Kafka."""
    try:
        event = json.loads(message.value)
        event_type = event.get("event_type")
        customer_data = event.get("customer")
        local_customer_id = customer_data.get("id")
        stripe_customer_id = customer_data.get("stripe_customer_id")

        logger.info(f"Processing event: {event_type} for local customer ID: {local_customer_id}")

        if event_type == "customer_created":
            try:
                stripe_customer = stripe.Customer.create(
                    name=customer_data.get("name"),
                    email=customer_data.get("email"),
                    metadata={'local_db_id': local_customer_id}
                )
                # CRITICAL: Update our local DB with the new Stripe ID
                local_customer = db.query(Customer).filter(Customer.id == local_customer_id).first()
                if local_customer:
                    local_customer.stripe_customer_id = stripe_customer.id
                    db.commit()
                    logger.info(f"Created Stripe customer {stripe_customer.id} and linked to local ID {local_customer_id}")
            except stripe.error.StripeError as e:
                logger.error(f"Stripe API error on create: {e}")

        elif event_type == "customer_updated":
            if not stripe_customer_id: return
            try:
                stripe.Customer.modify(stripe_customer_id, name=customer_data.get("name"), email=customer_data.get("email"))
                logger.info(f"Updated Stripe customer {stripe_customer_id}")
            except stripe.error.StripeError as e:
                logger.error(f"Stripe API error on update: {e}")

        elif event_type == "customer_deleted":
            if not stripe_customer_id: return
            try:
                stripe.Customer.delete(stripe_customer_id)
                logger.info(f"Deleted Stripe customer {stripe_customer_id}")
            except stripe.error.StripeError as e:
                logger.error(f"Stripe API error on delete: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred in worker: {e}")

def main():
    consumer = None
    db = get_db_session()
    
    max_retries = 5
    retry_delay = 15  # seconds
    for attempt in range(max_retries):
        try:
            logger.info(f"Worker connecting to Kafka (attempt {attempt + 1}/{max_retries})...")
            consumer = KafkaConsumer(
                settings.KAFKA_CUSTOMER_TOPIC,
                bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                auto_offset_reset='earliest',
                group_id='stripe-sync-worker-group',
                consumer_timeout_ms=10000,
                # Short timeout to fail fast on connection attempts
                request_timeout_ms=15000 
            )
            logger.info("Successfully connected to Kafka.")
            break  # Exit loop on successful connection
        except Exception as e:
            logger.error(f"Failed to connect to Kafka: {e}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error("Could not connect to Kafka after several retries. Exiting.")
                if db: db.close()
                return

    try:
        logger.info("Worker listening for messages...")
        for message in consumer:
            process_message(message, db)
    except Exception as e:
        logger.error(f"Worker failed while processing messages: {e}")
    finally:
        if db: db.close()
        if consumer: consumer.close()
        logger.info("Worker shutting down.")

if __name__ == "__main__":
    main()