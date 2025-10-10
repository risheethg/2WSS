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
    """The main function for the worker, runs in an infinite loop."""
    db: Session = None
    consumer: KafkaConsumer = None

    while True:
        try:
            # Ensure we have a valid DB session
            if not db or not db.is_active:
                if db:
                    db.close()
                db = get_db_session()
                logger.info("Database session established/re-established.")

            # Setup Kafka consumer
            if not consumer:
                logger.info("Connecting to Kafka...")
                consumer = KafkaConsumer(
                    settings.KAFKA_CUSTOMER_TOPIC,
                    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
                    auto_offset_reset='earliest',
                    group_id='stripe-sync-worker-group',
                    request_timeout_ms=15000
                )
                logger.info("Successfully connected to Kafka. Listening for messages...")

            # This will block until a message is received
            for message in consumer:
                process_message(message, db)

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