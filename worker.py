import json
import time
from kafka import KafkaConsumer
import stripe
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.customer import Customer

# Configure Stripe client
stripe.api_key = settings.STRIPE_API_KEY

print("Worker starting...")
# Give Kafka a moment to be ready
time.sleep(15)

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

        print(f"Processing event: {event_type} for local customer ID: {local_customer_id}")

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
                    print(f"Created Stripe customer {stripe_customer.id} and linked to local ID {local_customer_id}")
            except stripe.error.StripeError as e:
                print(f"Stripe API error on create: {e}")

        elif event_type == "customer_updated":
            if not stripe_customer_id: return
            try:
                stripe.Customer.modify(stripe_customer_id, name=customer_data.get("name"), email=customer_data.get("email"))
                print(f"Updated Stripe customer {stripe_customer_id}")
            except stripe.error.StripeError as e:
                print(f"Stripe API error on update: {e}")

        elif event_type == "customer_deleted":
            if not stripe_customer_id: return
            try:
                stripe.Customer.delete(stripe_customer_id)
                print(f"Deleted Stripe customer {stripe_customer_id}")
            except stripe.error.StripeError as e:
                print(f"Stripe API error on delete: {e}")
    except Exception as e:
        print(f"An unexpected error occurred in worker: {e}")

def main():
    consumer = None
    db = get_db_session()
    print("Worker connecting to Kafka...")
    try:
        consumer = KafkaConsumer(
            settings.KAFKA_CUSTOMER_TOPIC,
            bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
            auto_offset_reset='earliest',
            group_id='stripe-sync-worker-group',
            consumer_timeout_ms=10000
        )
        print("Worker listening for messages...")
        for message in consumer:
            process_message(message, db)
    except Exception as e:
        print(f"Worker failed to connect or process: {e}")
    finally:
        if db: db.close()
        if consumer: consumer.close()

if __name__ == "__main__":
    main()