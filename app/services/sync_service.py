"""
Integration Sync State Service

This service tracks the synchronization state between local customers and external integrations,
preventing orphaned records and ensuring data consistency.
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, or_

from app.models.integrity import IntegrationSyncState, IntegrationSyncStateCreate, IntegrationSyncStateUpdate, IntegrationSyncStateInDB
from app.core.logger import logger


class IntegrationSyncService:
    """Service for managing integration synchronization states"""
    
    @staticmethod
    def create_sync_state(
        db: Session,
        customer_id: int,
        integration_name: str,
        external_id: str = None,
        sync_status: str = "pending"
    ) -> Optional[IntegrationSyncStateInDB]:
        """Create a new sync state record"""
        try:
            sync_state = IntegrationSyncState(
                customer_id=customer_id,
                integration_name=integration_name,
                external_id=external_id,
                sync_status=sync_status,
                last_sync_attempt=datetime.utcnow() if sync_status != "pending" else None
            )
            
            db.add(sync_state)
            db.commit()
            db.refresh(sync_state)
            
            logger.info(f"Created sync state for customer {customer_id}, integration: {integration_name}")
            return IntegrationSyncStateInDB.from_orm(sync_state)
            
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Sync state already exists for customer {customer_id}, integration: {integration_name}")
            # Return existing record
            return IntegrationSyncService.get_sync_state(db, customer_id, integration_name)
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating sync state: {e}")
            return None
    
    @staticmethod
    def get_sync_state(
        db: Session,
        customer_id: int,
        integration_name: str
    ) -> Optional[IntegrationSyncStateInDB]:
        """Get sync state for a customer and integration"""
        sync_state = db.query(IntegrationSyncState).filter(
            and_(
                IntegrationSyncState.customer_id == customer_id,
                IntegrationSyncState.integration_name == integration_name
            )
        ).first()
        
        return IntegrationSyncStateInDB.from_orm(sync_state) if sync_state else None
    
    @staticmethod
    def get_sync_state_by_external_id(
        db: Session,
        integration_name: str,
        external_id: str
    ) -> Optional[IntegrationSyncStateInDB]:
        """Get sync state by external ID"""
        sync_state = db.query(IntegrationSyncState).filter(
            and_(
                IntegrationSyncState.integration_name == integration_name,
                IntegrationSyncState.external_id == external_id
            )
        ).first()
        
        return IntegrationSyncStateInDB.from_orm(sync_state) if sync_state else None
    
    @staticmethod
    def update_sync_state(
        db: Session,
        customer_id: int,
        integration_name: str,
        external_id: str = None,
        sync_status: str = None,
        error_message: str = None,
        increment_retry: bool = False
    ) -> bool:
        """Update sync state"""
        try:
            sync_state = db.query(IntegrationSyncState).filter(
                and_(
                    IntegrationSyncState.customer_id == customer_id,
                    IntegrationSyncState.integration_name == integration_name
                )
            ).first()
            
            if not sync_state:
                logger.warning(f"Sync state not found for customer {customer_id}, integration: {integration_name}")
                return False
            
            # Update fields
            if external_id is not None:
                sync_state.external_id = external_id
            if sync_status is not None:
                sync_state.sync_status = sync_status
            if error_message is not None:
                sync_state.error_message = error_message
            if increment_retry:
                sync_state.retry_count += 1
            
            sync_state.last_sync_attempt = datetime.utcnow()
            
            db.commit()
            logger.info(f"Updated sync state for customer {customer_id}, integration: {integration_name}")
            return True
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error updating sync state: {e}")
            return False
    
    @staticmethod
    def mark_sync_success(
        db: Session,
        customer_id: int,
        integration_name: str,
        external_id: str
    ) -> bool:
        """Mark synchronization as successful"""
        return IntegrationSyncService.update_sync_state(
            db, customer_id, integration_name, external_id, "synced", None
        )
    
    @staticmethod
    def mark_sync_failed(
        db: Session,
        customer_id: int,
        integration_name: str,
        error_message: str,
        increment_retry: bool = True
    ) -> bool:
        """Mark synchronization as failed"""
        return IntegrationSyncService.update_sync_state(
            db, customer_id, integration_name, None, "failed", error_message, increment_retry
        )
    
    @staticmethod
    def mark_orphaned(
        db: Session,
        customer_id: int,
        integration_name: str,
        error_message: str = "Customer deleted locally but sync failed"
    ) -> bool:
        """Mark record as orphaned"""
        return IntegrationSyncService.update_sync_state(
            db, customer_id, integration_name, None, "orphaned", error_message
        )
    
    @staticmethod
    def delete_sync_state(
        db: Session,
        customer_id: int,
        integration_name: str
    ) -> bool:
        """Delete sync state record"""
        try:
            sync_state = db.query(IntegrationSyncState).filter(
                and_(
                    IntegrationSyncState.customer_id == customer_id,
                    IntegrationSyncState.integration_name == integration_name
                )
            ).first()
            
            if sync_state:
                db.delete(sync_state)
                db.commit()
                logger.info(f"Deleted sync state for customer {customer_id}, integration: {integration_name}")
                return True
            
            return False
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error deleting sync state: {e}")
            return False
    
    @staticmethod
    def get_failed_syncs(
        db: Session,
        integration_name: str = None,
        max_retries: int = 3,
        older_than_minutes: int = 5
    ) -> List[IntegrationSyncStateInDB]:
        """Get failed sync records that need retry"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=older_than_minutes)
        
        query = db.query(IntegrationSyncState).filter(
            and_(
                IntegrationSyncState.sync_status == "failed",
                IntegrationSyncState.retry_count < max_retries,
                or_(
                    IntegrationSyncState.last_sync_attempt < cutoff_time,
                    IntegrationSyncState.last_sync_attempt.is_(None)
                )
            )
        )
        
        if integration_name:
            query = query.filter(IntegrationSyncState.integration_name == integration_name)
        
        failed_syncs = query.all()
        return [IntegrationSyncStateInDB.from_orm(sync) for sync in failed_syncs]
    
    @staticmethod
    def get_orphaned_records(
        db: Session,
        integration_name: str = None
    ) -> List[IntegrationSyncStateInDB]:
        """Get orphaned records that need cleanup"""
        query = db.query(IntegrationSyncState).filter(
            IntegrationSyncState.sync_status == "orphaned"
        )
        
        if integration_name:
            query = query.filter(IntegrationSyncState.integration_name == integration_name)
        
        orphaned = query.all()
        return [IntegrationSyncStateInDB.from_orm(sync) for sync in orphaned]
    
    @staticmethod
    def get_pending_syncs(
        db: Session,
        integration_name: str = None,
        older_than_minutes: int = 1
    ) -> List[IntegrationSyncStateInDB]:
        """Get pending sync records that might be stuck"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=older_than_minutes)
        
        query = db.query(IntegrationSyncState).filter(
            and_(
                IntegrationSyncState.sync_status == "pending",
                IntegrationSyncState.created_at < cutoff_time
            )
        )
        
        if integration_name:
            query = query.filter(IntegrationSyncState.integration_name == integration_name)
        
        pending = query.all()
        return [IntegrationSyncStateInDB.from_orm(sync) for sync in pending]
    
    @staticmethod
    def cleanup_old_records(
        db: Session,
        days_old: int = 30
    ) -> int:
        """Clean up old sync state records"""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            # Only delete successful syncs that are old
            deleted_count = db.query(IntegrationSyncState).filter(
                and_(
                    IntegrationSyncState.sync_status == "synced",
                    IntegrationSyncState.updated_at < cutoff_date
                )
            ).delete()
            
            db.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old sync state records")
            
            return deleted_count
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error cleaning up old sync state records: {e}")
            return 0
    
    @staticmethod
    def get_customer_sync_status(
        db: Session,
        customer_id: int
    ) -> Dict[str, Dict[str, Any]]:
        """Get sync status for all integrations for a customer"""
        sync_states = db.query(IntegrationSyncState).filter(
            IntegrationSyncState.customer_id == customer_id
        ).all()
        
        status = {}
        for sync_state in sync_states:
            status[sync_state.integration_name] = {
                "external_id": sync_state.external_id,
                "status": sync_state.sync_status,
                "last_attempt": sync_state.last_sync_attempt,
                "retry_count": sync_state.retry_count,
                "error": sync_state.error_message
            }
        
        return status
    
    @staticmethod
    def get_integration_health(
        db: Session,
        integration_name: str
    ) -> Dict[str, Any]:
        """Get health statistics for an integration"""
        from sqlalchemy import func
        
        # Get counts by status
        status_counts = db.query(
            IntegrationSyncState.sync_status,
            func.count(IntegrationSyncState.id).label('count')
        ).filter(
            IntegrationSyncState.integration_name == integration_name
        ).group_by(IntegrationSyncState.sync_status).all()
        
        # Get recent failure rate
        recent_cutoff = datetime.utcnow() - timedelta(hours=1)
        recent_attempts = db.query(func.count(IntegrationSyncState.id)).filter(
            and_(
                IntegrationSyncState.integration_name == integration_name,
                IntegrationSyncState.last_sync_attempt >= recent_cutoff
            )
        ).scalar()
        
        recent_failures = db.query(func.count(IntegrationSyncState.id)).filter(
            and_(
                IntegrationSyncState.integration_name == integration_name,
                IntegrationSyncState.sync_status == "failed",
                IntegrationSyncState.last_sync_attempt >= recent_cutoff
            )
        ).scalar()
        
        return {
            "integration": integration_name,
            "status_counts": {status: count for status, count in status_counts},
            "recent_attempts": recent_attempts or 0,
            "recent_failures": recent_failures or 0,
            "recent_failure_rate": (recent_failures / recent_attempts * 100) if recent_attempts else 0
        }


# Global service instance
sync_service = IntegrationSyncService()