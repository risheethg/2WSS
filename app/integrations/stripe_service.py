import stripe
from sqlalchemy.orm import Session
from typing import Dict, Any, Optional

from .base import BaseIntegrationService
from app.core.config import settings
from app.repos.customer_repo import customer_repo
from app.models import customer as customer_model
from app.core.logger import logger
from app.services.conflict_service import conflict_service
from app.services.customer_service import customer_service
from sqlalchemy.exc import IntegrityError


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
                
        except Exception as e:
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
            
        except Exception as e:
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
            
        except Exception as e:
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
        except Exception as e:
            if "SignatureVerificationError" in str(type(e)):
                logger.error("Invalid Stripe webhook signature")
                return False
            else:
                logger.error(f"Error verifying Stripe webhook signature: {e}")
                return False

    def _handle_customer_upsert(self, stripe_customer: dict, db: Session) -> bool:
        """
        Handle Stripe customer create/update with improved idempotency and conflict resolution.
        
        Features:
        - Idempotent processing (safe to run multiple times)
        - Out-of-order event handling (update before create)
        - Email conflict resolution with configurable strategies
        """
        try:
            stripe_customer_id = stripe_customer.get("id")
            email = stripe_customer.get("email", "")
            name = stripe_customer.get("name") or ""
            
            logger.info(f"Processing Stripe customer {stripe_customer_id} with email {email}")
            
            # Step 1: Check if we already have this customer linked by Stripe ID (idempotency)
            existing_stripe_customer = customer_repo.get_by_stripe_id(db, stripe_id=stripe_customer_id)
            
            if existing_stripe_customer:
                # Idempotent update - safe to run multiple times
                return self._update_existing_stripe_customer(db, existing_stripe_customer, stripe_customer)
            
            # Step 2: Handle new customer or out-of-order events
            return self._handle_new_or_unlinked_customer(db, stripe_customer)
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error handling Stripe customer upsert: {e}")
            return False

    def _update_existing_stripe_customer(self, db: Session, existing_customer, stripe_customer: dict) -> bool:
        """Update existing customer that's already linked to Stripe (idempotent)"""
        stripe_customer_id = stripe_customer.get("id")
        email = stripe_customer.get("email", "")
        name = stripe_customer.get("name") or ""
        
        try:
            logger.info(f"Updating existing customer {existing_customer.id} linked to Stripe {stripe_customer_id}")
            
            # Check for email conflicts before updating
            if email and email != existing_customer.email:
                conflicting_customer = customer_repo.get_by_field(db, "email", email)
                if conflicting_customer and conflicting_customer.id != existing_customer.id:
                    logger.warning(f"Email conflict: {email} already belongs to customer {conflicting_customer.id}")
                    # Keep existing email, only update name
                    update_data = customer_model.CustomerUpdate(name=name, email=existing_customer.email)
                else:
                    # Safe to update both name and email
                    update_data = customer_model.CustomerUpdate(name=name, email=email)
            else:
                # No email change or email is the same
                update_data = customer_model.CustomerUpdate(name=name, email=existing_customer.email)
            
            # Use webhook method to prevent circular updates
            updated_customer = customer_service.update_customer_from_webhook(db, existing_customer.id, update_data)
            if updated_customer:
                logger.info(f"Successfully updated customer {existing_customer.id}")
                return True
            else:
                logger.error(f"Failed to update customer {existing_customer.id}")
                return False
                
        except IntegrityError as integrity_error:
            # Handle email constraint violations
            db.rollback()
            success, message = conflict_service.handle_email_conflict(db, stripe_customer, integrity_error)
            logger.info(f"Handled email conflict: {message}")
            return success
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update existing Stripe customer {stripe_customer_id}: {e}")
            return False

    def _handle_new_or_unlinked_customer(self, db: Session, stripe_customer: dict) -> bool:
        """Handle new customer or out-of-order events (customer not yet linked to Stripe)"""
        stripe_customer_id = stripe_customer.get("id")
        email = stripe_customer.get("email", "")
        name = stripe_customer.get("name") or ""
        
        if not email:
            logger.warning(f"Skipping Stripe customer {stripe_customer_id} - no email provided")
            return True  # Not an error, just skip
        
        # Check if a local customer exists with this email (out-of-order handling)
        existing_by_email = customer_repo.get_by_field(db, "email", email)
        
        if existing_by_email:
            return self._link_existing_customer_to_stripe(db, existing_by_email, stripe_customer)
        else:
            return self._create_new_customer_from_stripe(db, stripe_customer)

    def _link_existing_customer_to_stripe(self, db: Session, existing_customer, stripe_customer: dict) -> bool:
        """Link existing local customer to Stripe (handles out-of-order events)"""
        stripe_customer_id = stripe_customer.get("id")
        name = stripe_customer.get("name") or ""
        
        try:
            if existing_customer.stripe_customer_id:
                logger.warning(f"Customer {existing_customer.id} already linked to Stripe {existing_customer.stripe_customer_id}")
                return True  # Already linked, idempotent
            
            # Link existing customer to Stripe
            logger.info(f"Linking existing customer {existing_customer.id} to Stripe {stripe_customer_id}")
            
            # Use webhook method to update Stripe ID (prevents circular updates)
            updated_customer = customer_service.update_stripe_id_from_webhook(db, existing_customer.id, stripe_customer_id)
            
            if updated_customer and name and name != existing_customer.name:
                # Also update name if provided and different
                update_data = customer_model.CustomerUpdate(name=name, email=existing_customer.email)
                customer_service.update_customer_from_webhook(db, existing_customer.id, update_data)
            
            if updated_customer:
                logger.info(f"Successfully linked customer {existing_customer.id} to Stripe")
                return True
            else:
                logger.error(f"Could not find customer {existing_customer.id} to link")
                return False
                
        except IntegrityError as integrity_error:
            # This shouldn't happen if we checked properly, but just in case
            db.rollback()
            success, message = conflict_service.handle_email_conflict(db, stripe_customer, integrity_error)
            logger.info(f"Handled unexpected email conflict during linking: {message}")
            return success
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to link customer {existing_customer.id} to Stripe: {e}")
            return False

    def _create_new_customer_from_stripe(self, db: Session, stripe_customer: dict) -> bool:
        """Create new local customer from Stripe data"""
        stripe_customer_id = stripe_customer.get("id")
        email = stripe_customer.get("email", "")
        name = stripe_customer.get("name") or ""
        
        try:
            logger.info(f"Creating new customer from Stripe for {email}")
            # Create customer data with Stripe ID
            customer_data = customer_model.CustomerCreate(name=name, email=email)
            
            # Use webhook method to prevent circular updates
            new_customer = customer_service.create_customer_from_webhook(db, customer_data)
            
            # Now link to Stripe ID using webhook method
            customer_service.update_stripe_id_from_webhook(db, new_customer.id, stripe_customer_id)
            
            logger.info(f"Successfully created customer {new_customer.id} for Stripe {stripe_customer_id}")
            return True
            
        except IntegrityError as integrity_error:
            # Handle email constraint violations
            db.rollback()
            success, message = conflict_service.handle_email_conflict(db, stripe_customer, integrity_error)
            logger.info(f"Handled email conflict during creation: {message}")
            return success
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create customer for Stripe {stripe_customer_id}: {e}")
            return False

    def _handle_customer_deleted(self, stripe_customer: dict, db: Session) -> bool:
        try:
            stripe_customer_id = stripe_customer.get("id")
            logger.info(f"Deactivating local customer linked to Stripe ID {stripe_customer_id}.")
            
            # Find the customer by Stripe ID first
            existing_customer = customer_repo.get_by_stripe_id(db, stripe_id=stripe_customer_id)
            
            if existing_customer:
                # Use webhook method to deactivate (prevents circular updates)
                deactivated = customer_service.deactivate_customer_from_webhook(db, existing_customer.id)
                if deactivated:
                    logger.info(f"Successfully deactivated customer {existing_customer.id} linked to Stripe ID {stripe_customer_id}")
                else:
                    logger.error(f"Failed to deactivate customer {existing_customer.id}")
                    return False
            else:
                logger.warning(f"No local customer found for Stripe ID {stripe_customer_id}")
            
            return True  # Return success even if customer wasn't found locally
            
        except Exception as e:
            logger.error(f"Error handling Stripe customer deletion: {e}")
            return False