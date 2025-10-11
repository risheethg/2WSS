from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from app.repos.customer_repo import customer_repo
from app.repos.base import repository_registry
from app.models import customer as customer_model
from app.models.customer import CustomerInDB
from app.core import messaging

class CustomerService:
    def create_customer(self, db: Session, customer: customer_model.CustomerCreate) -> CustomerInDB:
        """Create customer using new repository interface"""
        customer_in_db = customer_repo.create(db, customer)
        customer_data = customer_in_db.model_dump()
        messaging.send_customer_event("customer_created", customer_data)
        return customer_in_db

    def update_customer(self, db: Session, customer_id: int, customer_update: customer_model.CustomerUpdate) -> Optional[CustomerInDB]:
        """Update customer using new repository interface"""
        updated_customer = customer_repo.update(db, customer_id, customer_update)
        if updated_customer:
            customer_data = updated_customer.model_dump()
            messaging.send_customer_event("customer_updated", customer_data)
        return updated_customer

    def delete_customer(self, db: Session, customer_id: int) -> bool:
        """Delete customer using new repository interface"""
        # Get customer data before deletion for event
        customer = customer_repo.get_by_id(db, customer_id)
        deleted = customer_repo.delete(db, customer_id)
        if deleted and customer:
            customer_data = customer.model_dump()
            messaging.send_customer_event("customer_deleted", customer_data)
        return deleted

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