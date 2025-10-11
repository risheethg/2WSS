import stripe
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from .base import BaseIntegrationService
from app.core.config import settings
from app.repos.customer_repo import customer_repo
from app.models import customer as customer_model
from app.core.logger import logger


class StripeIntegration(BaseIntegrationService):
    def __init__(self, enabled: bool = True):
        super().__init__("stripe", enabled)
        if self.enabled:
            stripe.api_key = settings.STRIPE_API_KEY
            logger.info("Stripe Integration initialized successfully.")

    def create_customer(self, customer_data: dict, db: Session) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            logger.warning("Stripe integration is disabled, skipping create_customer")
            return None

        try:
            local_customer_id = customer_data.get("id")
            
            # Create customer in Stripe
            stripe_customer = stripe.Customer.create(
                name=customer_data.get("name"),
                email=customer_data.get("email"),
                metadata={'local_db_id': local_customer_id}
            )
            
            # Update local customer with Stripe ID
            local_customer = db.query(customer_model.Customer).filter(
                customer_model.Customer.id == local_customer_id
            ).first()
            
            if local_customer:
                local_customer.stripe_customer_id = stripe_customer.id
                db.commit()
                logger.info(f"Created Stripe customer {stripe_customer.id} and linked to local ID {local_customer_id}")
                return {"stripe_customer_id": stripe_customer.id}
            else:
                logger.error(f"Local customer with ID {local_customer_id} not found for Stripe linking")
                return None
                
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error on create: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during customer creation in Stripe: {e}")
            return None

    def update_customer(self, customer_data: dict, db: Session) -> bool:
        if not self.enabled:
            logger.warning("Stripe integration is disabled, skipping update_customer")
            return False

        stripe_customer_id = customer_data.get("stripe_customer_id")
        if not stripe_customer_id:
            logger.warning(f"No Stripe customer ID found for customer {customer_data.get('id')}, skipping update")
            return False

        try:
            stripe.Customer.modify(
                stripe_customer_id,
                name=customer_data.get("name"),
                email=customer_data.get("email")
            )
            logger.info(f"Updated Stripe customer {stripe_customer_id}")
            return True
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error on update: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during customer update in Stripe: {e}")
            return False

    def delete_customer(self, customer_data: dict, db: Session) -> bool:
        if not self.enabled:
            logger.warning("Stripe integration is disabled, skipping delete_customer")
            return False

        stripe_customer_id = customer_data.get("stripe_customer_id")
        if not stripe_customer_id:
            logger.warning(f"No Stripe customer ID found for customer {customer_data.get('id')}, skipping delete")
            return False

        try:
            stripe.Customer.delete(stripe_customer_id)
            logger.info(f"Deleted Stripe customer {stripe_customer_id}")
            return True
            
        except stripe.error.StripeError as e:
            logger.error(f"Stripe API error on delete: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error during customer deletion in Stripe: {e}")
            return False

    def handle_webhook_event(self, event_type: str, payload: dict, db: Session) -> bool:
        if not self.enabled:
            logger.warning("Stripe integration is disabled, skipping webhook event")
            return False

        try:
            logger.info(f"Processing Stripe webhook event: {event_type}")
            
            if event_type in ['customer.created', 'customer.updated']:
                return self._handle_customer_upsert(payload, db)
            elif event_type == 'customer.deleted':
                return self._handle_customer_deleted(payload, db)
            else:
                logger.info(f"Unhandled Stripe event type: {event_type}")
                return True  # Return True for unhandled but valid events
                
        except Exception as e:
            logger.error(f"Error handling Stripe webhook event {event_type}: {e}")
            return False

    def verify_webhook_signature(self, payload: bytes, signature: str, secret: str) -> bool:
        try:
            stripe.Webhook.construct_event(payload, signature, secret)
            return True
        except stripe.error.SignatureVerificationError:
            logger.error("Invalid Stripe webhook signature")
            return False
        except Exception as e:
            logger.error(f"Error verifying Stripe webhook signature: {e}")
            return False

    def _handle_customer_upsert(self, stripe_customer: dict, db: Session) -> bool:
        try:
            stripe_customer_id = stripe_customer.get("id")
            
            # Check if we already have this customer linked by Stripe ID
            customer = customer_repo.get_by_stripe_id(db, stripe_id=stripe_customer_id)
            
            customer_data = customer_model.CustomerUpdate(
                name=stripe_customer.get("name") or "",
                email=stripe_customer.get("email") or ""
            )

            if customer:
                # Update the existing customer
                logger.info(f"Updating local customer {customer.id} from Stripe event.")
                customer_repo.update_by_stripe_id(db, stripe_id=stripe_customer_id, customer_data=customer_data)
            else:
                # If not found by Stripe ID, check by email to link accounts
                existing_by_email = customer_repo.get_by_email(db, email=customer_data.email)
                if existing_by_email and not existing_by_email.stripe_customer_id:
                    logger.info(f"Linking existing local customer {existing_by_email.id} to Stripe ID {stripe_customer_id}.")
                    existing_by_email.stripe_customer_id = stripe_customer_id
                    existing_by_email.name = customer_data.name
                    existing_by_email.email = customer_data.email
                    db.commit()
                else:
                    # If no customer exists, create a new one
                    logger.info(f"Creating new local customer from Stripe event for {customer_data.email}.")
                    customer_repo.create_with_stripe_id(db, customer=customer_data, stripe_id=stripe_customer_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling Stripe customer upsert: {e}")
            return False

    def _handle_customer_deleted(self, stripe_customer: dict, db: Session) -> bool:
        try:
            stripe_customer_id = stripe_customer.get("id")
            logger.info(f"Deleting local customer linked to Stripe ID {stripe_customer_id}.")
            
            deleted_customer = customer_repo.delete_by_stripe_id(db, stripe_id=stripe_customer_id)
            
            if deleted_customer:
                logger.info(f"Successfully deleted local customer linked to Stripe ID {stripe_customer_id}")
            else:
                logger.warning(f"No local customer found for Stripe ID {stripe_customer_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error handling Stripe customer deletion: {e}")
            return False