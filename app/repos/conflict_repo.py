from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from datetime import datetime
import json

from app.models.conflict import DataConflict, ConflictCreate, ConflictInDB, ConflictStatus
from app.core.logger import logger


class ConflictRepository:
    """Repository for data conflict management"""

    def create_conflict(self, db: Session, conflict_data: ConflictCreate) -> ConflictInDB:
        """Create a new data conflict record"""
        try:
            webhook_json = json.dumps(conflict_data.webhook_event_data)
            
            db_conflict = DataConflict(
                conflict_type=conflict_data.conflict_type,
                entity_type=conflict_data.entity_type,
                external_system=conflict_data.external_system,
                external_id=conflict_data.external_id,
                conflict_field=conflict_data.conflict_field,
                conflict_value=conflict_data.conflict_value,
                existing_entity_id=conflict_data.existing_entity_id,
                webhook_event_data=webhook_json,
                error_message=conflict_data.error_message
            )
            
            db.add(db_conflict)
            db.commit()
            db.refresh(db_conflict)
            
            logger.warning(f"Created conflict record {db_conflict.id}: {conflict_data.conflict_type}")
            return ConflictInDB.from_orm(db_conflict)
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create conflict record: {e}")
            raise

    def get_pending_conflicts(self, db: Session, limit: int = 50) -> List[ConflictInDB]:
        """Get pending conflicts for review"""
        conflicts = db.query(DataConflict).filter(
            DataConflict.status == ConflictStatus.PENDING.value
        ).order_by(DataConflict.created_at.desc()).limit(limit).all()
        
        return [ConflictInDB.from_orm(conflict) for conflict in conflicts]

    def get_conflict_by_id(self, db: Session, conflict_id: int) -> Optional[ConflictInDB]:
        """Get conflict by ID"""
        conflict = db.query(DataConflict).filter(DataConflict.id == conflict_id).first()
        return ConflictInDB.from_orm(conflict) if conflict else None

    def resolve_conflict(self, db: Session, conflict_id: int, strategy: str, 
                        resolved_by: str = "admin", notes: str = None) -> bool:
        """Mark conflict as resolved"""
        try:
            conflict = db.query(DataConflict).filter(DataConflict.id == conflict_id).first()
            if not conflict:
                return False
            
            conflict.status = ConflictStatus.RESOLVED.value
            conflict.resolution_strategy = strategy
            conflict.resolved_at = datetime.utcnow()
            conflict.resolved_by = resolved_by
            conflict.resolution_notes = notes
            
            db.commit()
            logger.info(f"Resolved conflict {conflict_id} with strategy: {strategy}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to resolve conflict {conflict_id}: {e}")
            return False

    def get_conflicts_by_external_id(self, db: Session, external_system: str, 
                                   external_id: str) -> List[ConflictInDB]:
        """Get conflicts for a specific external entity"""
        conflicts = db.query(DataConflict).filter(
            DataConflict.external_system == external_system,
            DataConflict.external_id == external_id
        ).order_by(DataConflict.created_at.desc()).all()
        
        return [ConflictInDB.from_orm(conflict) for conflict in conflicts]

    def check_for_similar_conflicts(self, db: Session, conflict_type: str, 
                                  conflict_field: str, conflict_value: str,
                                  external_system: str) -> List[ConflictInDB]:
        """Check for similar unresolved conflicts"""
        conflicts = db.query(DataConflict).filter(
            DataConflict.conflict_type == conflict_type,
            DataConflict.conflict_field == conflict_field,
            DataConflict.conflict_value == conflict_value,
            DataConflict.external_system == external_system,
            DataConflict.status == ConflictStatus.PENDING.value
        ).all()
        
        return [ConflictInDB.from_orm(conflict) for conflict in conflicts]

    def get_conflict_statistics(self, db: Session) -> Dict[str, Any]:
        """Get conflict statistics for monitoring"""
        total_conflicts = db.query(DataConflict).count()
        pending_conflicts = db.query(DataConflict).filter(
            DataConflict.status == ConflictStatus.PENDING.value
        ).count()
        resolved_conflicts = db.query(DataConflict).filter(
            DataConflict.status == ConflictStatus.RESOLVED.value
        ).count()
        
        # Get most common conflict types
        from sqlalchemy import func
        common_types = db.query(
            DataConflict.conflict_type,
            func.count(DataConflict.id).label('count')
        ).group_by(DataConflict.conflict_type).order_by(
            func.count(DataConflict.id).desc()
        ).limit(5).all()
        
        return {
            "total_conflicts": total_conflicts,
            "pending_conflicts": pending_conflicts,
            "resolved_conflicts": resolved_conflicts,
            "common_conflict_types": [
                {"type": ct.conflict_type, "count": ct.count} 
                for ct in common_types
            ]
        }


# Global repository instance
conflict_repo = ConflictRepository()