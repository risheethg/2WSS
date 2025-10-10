from sqlalchemy import Column, Integer, String, Boolean
from pydantic import BaseModel, EmailStr, ConfigDict

from app.core.database import Base

class Customer(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    email = Column(String, unique=True, index=True)
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
    is_active: bool

    model_config = ConfigDict(from_attributes=True) # formerly orm_mode