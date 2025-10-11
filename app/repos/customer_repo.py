from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from sqlalchemy.exc import IntegrityError
from sqlalchemy import or_

from app.repos.base import BaseRepository
from app.models import customer as customer_model
from app.models.customer import CustomerInDB


class CustomerRepo(BaseRepository[customer_model.Customer, customer_model.CustomerCreate, customer_model.CustomerUpdate, CustomerInDB]):
    # BaseRepository interface methods
    def get_by_id(self, db: Session, entity_id: int) -> Optional[CustomerInDB]:
        """Get customer by ID (BaseRepository interface)"""
        customer = db.query(customer_model.Customer).filter(
            customer_model.Customer.id == entity_id,
            customer_model.Customer.is_active == True
        ).first()
        return CustomerInDB.from_orm(customer) if customer else None
    
    def get_by_field(self, db: Session, field_name: str, field_value: Any) -> Optional[CustomerInDB]:
        """Get customer by any field (BaseRepository interface)"""
        if not hasattr(customer_model.Customer, field_name):
            return None
        
        customer = db.query(customer_model.Customer).filter(
            getattr(customer_model.Customer, field_name) == field_value,
            customer_model.Customer.is_active == True
        ).first()
        return CustomerInDB.from_orm(customer) if customer else None

    # Legacy method for backward compatibility
    def get(self, db: Session, customer_id: int, include_inactive: bool = False) -> Optional[customer_model.Customer]:
        query = db.query(customer_model.Customer).filter(customer_model.Customer.id == customer_id)
        if not include_inactive:
            query = query.filter(customer_model.Customer.is_active == True)
        return query.first()
    
    # ADD THIS NEW METHOD
    def get_by_email(self, db: Session, email: str) -> Optional[customer_model.Customer]:
        return db.query(customer_model.Customer).filter(customer_model.Customer.email == email).first()

    def get_all(self, db: Session, skip: int = 0, limit: int = 100, filters: Dict[str, Any] = None) -> List[CustomerInDB]:
        """Get all customers (BaseRepository interface)"""
        query = db.query(customer_model.Customer).filter(customer_model.Customer.is_active == True)
        
        # Apply filters if provided
        if filters:
            for field, value in filters.items():
                if hasattr(customer_model.Customer, field):
                    query = query.filter(getattr(customer_model.Customer, field) == value)
        
        customers = query.offset(skip).limit(limit).all()
        return [CustomerInDB.from_orm(customer) for customer in customers]

    def create(self, db: Session, entity_data: customer_model.CustomerCreate) -> CustomerInDB:
        """Create customer (BaseRepository interface)"""
        try:
            db_customer = customer_model.Customer(name=entity_data.name, email=entity_data.email)
            db.add(db_customer)
            db.commit()
            db.refresh(db_customer)
            return CustomerInDB.from_orm(db_customer)
        except IntegrityError as e:
            db.rollback()
            if "email" in str(e.orig):
                raise ValueError(f"Customer with email '{entity_data.email}' already exists")
            raise ValueError(f"Failed to create customer: {str(e)}")

    def update(self, db: Session, entity_id: int, update_data: customer_model.CustomerUpdate) -> Optional[CustomerInDB]:
        """Update customer (BaseRepository interface)"""
        customer = db.query(customer_model.Customer).filter(
            customer_model.Customer.id == entity_id,
            customer_model.Customer.is_active == True
        ).first()
        
        if not customer:
            return None
        
        customer.name = update_data.name
        customer.email = update_data.email
        
        try:
            db.commit()
            db.refresh(customer)
            return CustomerInDB.from_orm(customer)
        except IntegrityError as e:
            db.rollback()
            if "email" in str(e.orig):
                raise ValueError(f"Email '{update_data.email}' is already taken")
            raise ValueError(f"Failed to update customer: {str(e)}")

    def delete(self, db: Session, entity_id: int) -> bool:
        """Delete customer (BaseRepository interface)"""
        customer = db.query(customer_model.Customer).filter(
            customer_model.Customer.id == entity_id,
            customer_model.Customer.is_active == True
        ).first()
        
        if not customer:
            return False
        
        customer.is_active = False
        db.commit()
        return True
    
    def search(self, db: Session, query: str) -> List[CustomerInDB]:
        """Search customers (BaseRepository interface)"""
        customers = db.query(customer_model.Customer).filter(
            customer_model.Customer.is_active == True,
            or_(
                customer_model.Customer.name.ilike(f"%{query}%"),
                customer_model.Customer.email.ilike(f"%{query}%")
            )
        ).all()
        return [CustomerInDB.from_orm(customer) for customer in customers]

    # Convenience methods for backward compatibility and integrations
    def get_by_stripe_id(self, db: Session, stripe_id: str) -> Optional[CustomerInDB]:
        """Get customer by Stripe ID"""
        return self.get_by_field(db, "stripe_customer_id", stripe_id)
    
    def create_with_integration_id(self, db: Session, entity_data: customer_model.CustomerCreate, 
                                  integration_field: str, integration_id: str) -> CustomerInDB:
        """Create customer with integration-specific ID"""
        try:
            customer_dict = {
                "name": entity_data.name,
                "email": entity_data.email,
                integration_field: integration_id
            }
            
            db_customer = customer_model.Customer(**customer_dict)
            db.add(db_customer)
            db.commit()
            db.refresh(db_customer)
            return CustomerInDB.from_orm(db_customer)
        except IntegrityError as e:
            db.rollback()
            if "email" in str(e.orig):
                raise ValueError(f"Customer with email '{entity_data.email}' already exists")
            raise ValueError(f"Failed to create customer: {str(e)}")

    def create_with_stripe_id(self, db: Session, customer: customer_model.CustomerCreate, stripe_id: str) -> customer_model.Customer:
        """Legacy method for backward compatibility"""
        db_customer = customer_model.Customer(name=customer.name, email=customer.email, stripe_customer_id=stripe_id)
        db.add(db_customer)
        db.commit()
        db.refresh(db_customer)
        return db_customer

    def update_by_stripe_id(self, db: Session, stripe_id: str, customer_data: customer_model.CustomerUpdate) -> Optional[customer_model.Customer]:
        db_customer = self.get_by_stripe_id(db, stripe_id)
        if db_customer:
            db_customer.name = customer_data.name
            db_customer.email = customer_data.email
            db.commit()
            db.refresh(db_customer)
        return db_customer

    def delete_by_stripe_id(self, db: Session, stripe_id: str) -> bool:
        """Delete customer by Stripe ID (soft delete)"""
        # Get the actual database model, not the Pydantic model
        db_customer = db.query(customer_model.Customer).filter(
            customer_model.Customer.stripe_customer_id == stripe_id,
            customer_model.Customer.is_active == True
        ).first()
        
        if db_customer:
            # Soft delete
            db_customer.is_active = False
            db.commit()
            return True
        return False

customer_repo = CustomerRepo()