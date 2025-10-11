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
                logger.warning(f"Local customer with ID {local_customer_id} not found for Stripe linking - customer may have been deleted")
                # Still return success since Stripe customer was created successfully
                return {"stripe_customer_id": stripe_customer.id}
                
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
            email = stripe_customer.get("email", "")
            name = stripe_customer.get("name") or ""
            
            # Check if we already have this customer linked by Stripe ID
            customer = customer_repo.get_by_stripe_id(db, stripe_id=stripe_customer_id)
            
            if customer:
                # Update existing customer linked by Stripe ID
                logger.info(f"Updating local customer {customer.id} from Stripe event.")
                try:
                    customer.name = name
                    # Only update email if it's different and not conflicting
                    if email and email != customer.email:
                        existing_email_customer = customer_repo.get_by_email(db, email=email)
                        if existing_email_customer and existing_email_customer.id != customer.id:
                            logger.warning(f"Cannot update customer {customer.id} email to {email} - already exists")
                        else:
                            customer.email = email
                    db.commit()
                    logger.info(f"Successfully updated customer {customer.id}")
                except Exception as update_error:
                    db.rollback()
                    logger.error(f"Failed to update customer {customer.id}: {update_error}")
                    return False
            else:
                # Check if customer exists by email
                existing_by_email = customer_repo.get_by_email(db, email=email) if email else None
                
                if existing_by_email:
                    if not existing_by_email.stripe_customer_id:
                        # Link existing customer to Stripe
                        logger.info(f"Linking existing customer {existing_by_email.id} to Stripe ID {stripe_customer_id}")
                        existing_by_email.stripe_customer_id = stripe_customer_id
                        existing_by_email.name = name
                        db.commit()
                        logger.info(f"Successfully linked customer {existing_by_email.id}")
                    else:
                        logger.warning(f"Customer with email {email} already linked to Stripe ID {existing_by_email.stripe_customer_id}")
                elif email:
                    # Create new customer
                    logger.info(f"Creating new customer from Stripe for {email}")
                    customer_data = customer_model.CustomerCreate(name=name, email=email)
                    customer_repo.create_with_stripe_id(db, customer=customer_data, stripe_id=stripe_customer_id)
                    logger.info(f"Successfully created customer for {email}")
                else:
                    logger.warning(f"Skipping Stripe customer {stripe_customer_id} - no email provided")
            
            return True
            
        except Exception as e:
            db.rollback()
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