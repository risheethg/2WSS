from sqlalchemy.orm import Session
from typing import Optional, List
from app.models import customer as customer_model


class CustomerRepo:
    def get(self, db: Session, customer_id: int, include_inactive: bool = False) -> Optional[customer_model.Customer]:
        query = db.query(customer_model.Customer).filter(customer_model.Customer.id == customer_id)
        if not include_inactive:
            query = query.filter(customer_model.Customer.is_active == True)
        return query.first()
    
    # ADD THIS NEW METHOD
    def get_by_email(self, db: Session, email: str) -> Optional[customer_model.Customer]:
        return db.query(customer_model.Customer).filter(customer_model.Customer.email == email).first()

    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> List[customer_model.Customer]:
        return db.query(customer_model.Customer).filter(customer_model.Customer.is_active == True).offset(skip).limit(limit).all()

    def create(self, db: Session, customer: customer_model.CustomerCreate) -> customer_model.Customer:
        db_customer = customer_model.Customer(name=customer.name, email=customer.email)
        db.add(db_customer)
        db.commit()
        db.refresh(db_customer)
        return db_customer

    def update(self, db: Session, customer_id: int, customer_data: customer_model.CustomerUpdate) -> Optional[customer_model.Customer]:
        db_customer = self.get(db, customer_id)
        if db_customer:
            db_customer.name = customer_data.name
            db_customer.email = customer_data.email
            db.commit()
            db.refresh(db_customer)
        return db_customer

    def delete(self, db: Session, customer_id: int) -> Optional[customer_model.Customer]:
        db_customer = self.get(db, customer_id)
        if db_customer:
            db_customer.is_active = False
            db.add(db_customer)
            db.commit()
            db.refresh(db_customer)
        return db_customer

    # METHODS FOR STRIPE INTEGRATION
    def get_by_stripe_id(self, db: Session, stripe_id: str) -> Optional[customer_model.Customer]:
        return db.query(customer_model.Customer).filter(customer_model.Customer.stripe_customer_id == stripe_id).first()

    def create_with_stripe_id(self, db: Session, customer: customer_model.CustomerCreate, stripe_id: str) -> customer_model.Customer:
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

    def delete_by_stripe_id(self, db: Session, stripe_id: str) -> Optional[customer_model.Customer]:
        db_customer = self.get_by_stripe_id(db, stripe_id)
        if db_customer:
            # If you have a soft delete (is_active=False), you would implement that here.
            db.delete(db_customer)
            db.commit()
        return db_customer

customer_repo = CustomerRepo()