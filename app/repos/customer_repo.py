from sqlalchemy.orm import Session
from typing import Optional, List
from app.models import customer as customer_model

class CustomerRepo:
    def get(self, db: Session, customer_id: int) -> Optional[customer_model.Customer]:
        return db.query(customer_model.Customer).filter(customer_model.Customer.id == customer_id).first()

    def get_all(self, db: Session, skip: int = 0, limit: int = 100) -> List[customer_model.Customer]:
        return db.query(customer_model.Customer).offset(skip).limit(limit).all()

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
            db.delete(db_customer)
            db.commit()
        return db_customer

customer_repo = CustomerRepo()