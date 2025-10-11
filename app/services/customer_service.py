from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.repos.customer_repo import customer_repo
from app.repos.base import repository_registry
from app.models import customer as customer_model
from app.models.customer import CustomerInDB
from app.core import messaging

class CustomerService:
    def create_customer(self, db: Session, customer: customer_model.CustomerCreate) -> CustomerInDB:
        """Create customer using outbox pattern for reliable event publishing"""
        try:
            # Start database transaction
            customer_in_db = customer_repo.create(db, customer)
            
            # Add event to outbox within the same transaction
            messaging.add_event_to_outbox(
                db=db,
                event_type="customer_created", 
                entity_type="customer",
                entity_data=customer_in_db.model_dump()
            )
            
            # Commit both customer creation and outbox event
            db.commit()
            return customer_in_db
            
        except Exception as e:
            db.rollback()
            raise

    def update_customer(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[CustomerInDB]:
        """Update customer using outbox pattern for reliable event publishing"""
        try:
            updated_customer = customer_repo.update(db, customer_id, customer_update)
            if updated_customer:
                # Add event to outbox within the same transaction
                messaging.add_event_to_outbox(
                    db=db,
                    event_type="customer_updated",
                    entity_type="customer", 
                    entity_data=updated_customer.model_dump()
                )
                db.commit()
            return updated_customer
            
        except Exception as e:
            db.rollback()
            raise

    def delete_customer(self, db: Session, customer_id: int) -> bool:
        """Delete customer using outbox pattern for reliable event publishing"""
        try:
            # Get customer data before deletion for event
            customer = customer_repo.get_by_id(db, customer_id)
            if not customer:
                return False
                
            deleted = customer_repo.delete(db, customer_id)
            if deleted:
                # Add event to outbox within the same transaction
                messaging.add_event_to_outbox(
                    db=db,
                    event_type="customer_deleted",
                    entity_type="customer",
                    entity_data=customer.model_dump()
                )
                db.commit()
            return deleted
            
        except Exception as e:
            db.rollback()
            raise

    def get_customer(self, db: Session, customer_id: int) -> Optional[CustomerInDB]:
        """Get customer using new repository interface"""
        return customer_repo.get_by_id(db, customer_id)

    def get_all_customers(self, db: Session, skip: int = 0, limit: int = 100, filters: Dict[str, Any] = None) -> List[CustomerInDB]:
        """Get all customers with optional filtering"""
        return customer_repo.get_all(db, skip, limit, filters)
    
    def search_customers(self, db: Session, query: str) -> List[CustomerInDB]:
        """Search customers by name or email"""
        return customer_repo.search(db, query)
    
    # Convenience methods
    def get_customer_by_email(self, db: Session, email: str) -> Optional[CustomerInDB]:
        """Get customer by email"""
        return customer_repo.get_by_field(db, "email", email)
    
    def get_customer_by_stripe_id(self, db: Session, stripe_id: str) -> Optional[CustomerInDB]:
        """Get customer by Stripe ID"""
        return customer_repo.get_by_stripe_id(db, stripe_id)
    
    # Webhook-specific methods (DO NOT trigger outbound events to prevent sync loops)
    
    def update_customer_from_webhook(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[CustomerInDB]:
        """
        Update customer from webhook data - DOES NOT trigger outbound events.
        Use this method when processing inbound webhooks from Stripe to prevent sync loops.
        """
        try:
            updated_customer = customer_repo.update(db, customer_id, customer_update)
            if updated_customer:
                # NOTE: Deliberately NOT adding to outbox to prevent circular updates
                db.commit()
            return updated_customer
            
        except Exception as e:
            db.rollback()
            raise
    
    def create_customer_from_webhook(self, db: Session, customer: customer_model.CustomerCreate) -> CustomerInDB:
        """
        Create customer from webhook data - DOES NOT trigger outbound events.
        Use this method when processing inbound webhooks from Stripe to prevent sync loops.
        """
        try:
            customer_in_db = customer_repo.create(db, customer)
            # NOTE: Deliberately NOT adding to outbox to prevent circular updates
            db.commit()
            return customer_in_db
            
        except Exception as e:
            db.rollback()
            raise
    
    def update_stripe_id_from_webhook(self, db: Session, customer_id: int, stripe_customer_id: str) -> Optional[CustomerInDB]:
        """
        Update customer's Stripe ID from webhook - DOES NOT trigger outbound events.
        Used during reconciliation or webhook processing.
        """
        try:
            customer = customer_repo.get_by_id(db, customer_id)
            if customer:
                customer.stripe_customer_id = stripe_customer_id
                db.commit()
                db.refresh(customer)
            return customer
            
        except Exception as e:
            db.rollback()
            raise
    
    def deactivate_customer_from_webhook(self, db: Session, customer_id: int) -> Optional[CustomerInDB]:
        """
        Deactivate customer from webhook data - DOES NOT trigger outbound events.
        Use this method when processing deletion webhooks from Stripe.
        """
        try:
            customer = customer_repo.get_by_id(db, customer_id)
            if customer:
                customer.is_active = False
                db.commit()
                db.refresh(customer)
            return customer
            
        except Exception as e:
            db.rollback()
            raise


customer_service = CustomerService()