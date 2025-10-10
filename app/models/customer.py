from sqlalchemy import Column, Integer, String, Boolean
from pydantic import BaseModel, EmailStr
from typing import Optional

from app.core.database import Base

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
    stripe_customer_id = Column(String, unique=True, index=True, nullable=True)
    is_active = Column(Boolean, default=True)


class CustomerBase(BaseModel):
    name: str
    email: EmailStr

class CustomerCreate(CustomerBase):
    pass

class CustomerUpdate(CustomerBase):
    pass

class CustomerInDB(CustomerBase):
    id: int
    name: str
    email: EmailStr
    is_active: bool
    stripe_customer_id: Optional[str] = None # ADD THIS

    class Config:
        from_attributes = True # Pydantic v2 equivalent of orm_mode