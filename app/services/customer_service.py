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
    


customer_service = CustomerService()