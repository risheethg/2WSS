"""
Abstract Repository Pattern for Swappable Table Operations

This provides a clean abstraction over different table schemas while
keeping PostgreSQL as the database. Perfect for:
- Adding new entity types (invoices, products, etc.)  
- Supporting different table structures
- Easy testing with mock repositories
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, TypeVar, Generic
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Generic types for entities
T = TypeVar('T')  # Database model type
CreateT = TypeVar('CreateT', bound=BaseModel)  # Create schema type  
UpdateT = TypeVar('UpdateT', bound=BaseModel)  # Update schema type
ResponseT = TypeVar('ResponseT', bound=BaseModel)  # Response schema type


class BaseRepository(ABC, Generic[T, CreateT, UpdateT, ResponseT]):
    """
    Abstract repository for any table/entity in PostgreSQL.
    
    Swap implementations for different entity types:
    - CustomerRepository -> customer table operations
    - InvoiceRepository -> invoice table operations  
    - ProductRepository -> product table operations
    """
    
    @abstractmethod
    def get_by_id(self, db: Session, entity_id: int) -> Optional[ResponseT]:
        """Get entity by ID"""
        pass
    
    @abstractmethod
    def get_by_field(self, db: Session, field_name: str, field_value: Any) -> Optional[ResponseT]:
        """Get entity by any field"""
        pass
    
    @abstractmethod
    def get_all(self, db: Session, skip: int = 0, limit: int = 100, filters: Dict[str, Any] = None) -> List[ResponseT]:
        """Get all entities with optional filtering"""
        pass
    
    @abstractmethod
    def create(self, db: Session, entity_data: CreateT) -> ResponseT:
        """Create new entity"""
        pass
    
    @abstractmethod
    def update(self, db: Session, entity_id: int, update_data: UpdateT) -> Optional[ResponseT]:
        """Update existing entity"""
        pass
    
    @abstractmethod
    def delete(self, db: Session, entity_id: int) -> bool:
        """Delete entity (soft delete recommended)"""
        pass
    
    @abstractmethod
    def search(self, db: Session, query: str) -> List[ResponseT]:
        """Search entities by text"""
        pass


class RepositoryRegistry:
    """
    Registry for managing different repository implementations.
    
    This allows your services to work with any entity type:
    - customers, invoices, products, orders, etc.
    """
    
    def __init__(self):
        self._repositories: Dict[str, BaseRepository] = {}
    
    def register(self, entity_name: str, repository: BaseRepository):
        """Register a repository for an entity type"""
        self._repositories[entity_name] = repository
    
    def get(self, entity_name: str) -> BaseRepository:
        """Get repository for entity type"""
        if entity_name not in self._repositories:
            raise ValueError(f"Repository for '{entity_name}' not found")
        return self._repositories[entity_name]
    
    def get_all(self) -> Dict[str, BaseRepository]:
        """Get all registered repositories"""
        return self._repositories.copy()


# Global repository registry
repository_registry = RepositoryRegistry()