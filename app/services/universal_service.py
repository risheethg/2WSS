"""
Universal Entity Service

Generic service that works with any repository implementation.
This makes your business logic completely independent of the entity type.
"""

from typing import List, Optional, Dict, Any, TypeVar
from sqlalchemy.orm import Session

from app.repos.base import repository_registry
from app.core import messaging

# Generic types
CreateT = TypeVar('CreateT')
UpdateT = TypeVar('UpdateT') 
ResponseT = TypeVar('ResponseT')


class UniversalEntityService:
    """
    Generic service that works with any entity type through repositories.
    
    This service can handle customers, invoices, products, orders, etc.
    Just swap the repository and you get full CRUD operations.
    """
    
    def __init__(self, entity_name: str):
        self.entity_name = entity_name
        
    def _get_repository(self):
        """Get repository for this entity type"""
        return repository_registry.get(self.entity_name)
    
    def create_entity(self, db: Session, entity_data: CreateT) -> ResponseT:
        """Create entity using appropriate repository"""
        repository = self._get_repository()
        entity = repository.create(db, entity_data)
        
        # Send event for integrations
        event_data = entity.model_dump() if hasattr(entity, 'model_dump') else entity.__dict__
        messaging.send_customer_event(f"{self.entity_name}_created", event_data)
        
        return entity
    
    def get_entity(self, db: Session, entity_id: int) -> Optional[ResponseT]:
        """Get entity by ID"""
        repository = self._get_repository()
        return repository.get_by_id(db, entity_id)
    
    def get_entity_by_field(self, db: Session, field_name: str, field_value: Any) -> Optional[ResponseT]:
        """Get entity by any field"""
        repository = self._get_repository()
        return repository.get_by_field(db, field_name, field_value)
    
    def update_entity(self, db: Session, entity_id: int, update_data: UpdateT) -> Optional[ResponseT]:
        """Update entity"""
        repository = self._get_repository()
        updated_entity = repository.update(db, entity_id, update_data)
        
        if updated_entity:
            event_data = updated_entity.model_dump() if hasattr(updated_entity, 'model_dump') else updated_entity.__dict__
            messaging.send_customer_event(f"{self.entity_name}_updated", event_data)
        
        return updated_entity
    
    def delete_entity(self, db: Session, entity_id: int) -> bool:
        """Delete entity"""
        repository = self._get_repository()
        
        # Get entity data before deletion for event
        entity = repository.get_by_id(db, entity_id)
        success = repository.delete(db, entity_id)
        
        if success and entity:
            event_data = entity.model_dump() if hasattr(entity, 'model_dump') else entity.__dict__
            messaging.send_customer_event(f"{self.entity_name}_deleted", event_data)
        
        return success
    
    def get_all_entities(self, db: Session, skip: int = 0, limit: int = 100, 
                        filters: Dict[str, Any] = None) -> List[ResponseT]:
        """Get all entities with optional filtering"""
        repository = self._get_repository()
        return repository.get_all(db, skip, limit, filters)
    
    def search_entities(self, db: Session, query: str) -> List[ResponseT]:
        """Search entities"""
        repository = self._get_repository()
        return repository.search(db, query)


def create_entity_service(entity_name: str) -> UniversalEntityService:
    """Factory function to create service for any entity type"""
    return UniversalEntityService(entity_name)


# Pre-configured services for common entities
customer_service = create_entity_service("customers")
invoice_service = create_entity_service("invoices")