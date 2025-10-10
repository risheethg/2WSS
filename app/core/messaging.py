import json
from kafka import KafkaProducer
from .config import settings

producer = KafkaProducer(
    bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
    value_serializer=lambda v: json.dumps(v).encode('utf-8')
)

def send_customer_event(event_type: str, customer_data: dict):
    """Sends a customer event to the Kafka topic."""
    message = {
        "event_type": event_type,
        "customer": customer_data
    }
    producer.send(settings.KAFKA_CUSTOMER_TOPIC, value=message)
    producer.flush()
    print(f"Sent event '{event_type}' for customer ID {customer_data.get('id')} to Kafka.")