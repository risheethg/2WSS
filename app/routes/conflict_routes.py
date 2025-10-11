"""
Conflict Management Admin Routes

Admin endpoints for viewing and resolving data conflicts.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional

from app.core.database import get_db
from app.core.response import response_handler
from app.repos.conflict_repo import conflict_repo
from app.services.conflict_service import conflict_service
from app.models.conflict import ConflictResolution, ConflictResolutionStrategy

router = APIRouter(
    prefix="/admin/conflicts",
    tags=["Admin - Conflicts"]
)


@router.get("/")
def get_conflicts(
    status: Optional[str] = Query(None, description="Filter by status: pending, resolved, rejected"),
    limit: int = Query(50, description="Maximum number of conflicts to return"),
    db: Session = Depends(get_db)
):
    """Get list of data conflicts"""
    try:
        if status == "pending" or status is None:
            conflicts = conflict_repo.get_pending_conflicts(db, limit=limit)
        else:
            # For now, just get pending conflicts. Could extend to filter by other statuses
            conflicts = conflict_repo.get_pending_conflicts(db, limit=limit)
        
        conflicts_data = [conflict.model_dump() for conflict in conflicts]
        
        return response_handler.success(
            data={
                "conflicts": conflicts_data,
                "count": len(conflicts_data)
            },
            message=f"Retrieved {len(conflicts_data)} conflicts"
        )
        
    except Exception as e:
        return response_handler.failure(
            message=f"Failed to retrieve conflicts: {str(e)}",
            status_code=500
        )


@router.get("/statistics")
def get_conflict_statistics(db: Session = Depends(get_db)):
    """Get conflict statistics for monitoring"""
    try:
        stats = conflict_repo.get_conflict_statistics(db)
        
        return response_handler.success(
            data=stats,
            message="Retrieved conflict statistics"
        )
        
    except Exception as e:
        return response_handler.failure(
            message=f"Failed to retrieve statistics: {str(e)}",
            status_code=500
        )


@router.get("/{conflict_id}")
def get_conflict_details(
    conflict_id: int,
    db: Session = Depends(get_db)
):
    """Get detailed information about a specific conflict"""
    try:
        conflict = conflict_repo.get_conflict_by_id(db, conflict_id)
        
        if not conflict:
            return response_handler.failure(
                message="Conflict not found",
                status_code=404
            )
        
        return response_handler.success(
            data=conflict.model_dump(),
            message="Retrieved conflict details"
        )
        
    except Exception as e:
        return response_handler.failure(
            message=f"Failed to retrieve conflict: {str(e)}",
            status_code=500
        )


@router.post("/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: int,
    resolution: ConflictResolution,
    db: Session = Depends(get_db)
):
    """Manually resolve a data conflict"""
    try:
        success, message = conflict_service.manually_resolve_conflict(
            db=db,
            conflict_id=conflict_id,
            strategy=resolution.strategy.value,
            resolved_by=resolution.resolved_by,
            notes=resolution.notes
        )
        
        if success:
            return response_handler.success(
                data={"conflict_id": conflict_id, "strategy": resolution.strategy.value},
                message=f"Conflict resolved successfully: {message}"
            )
        else:
            return response_handler.failure(
                message=f"Failed to resolve conflict: {message}",
                status_code=400
            )
        
    except Exception as e:
        return response_handler.failure(
            message=f"Error resolving conflict: {str(e)}",
            status_code=500
        )


@router.get("/external/{external_system}/{external_id}")
def get_conflicts_by_external_id(
    external_system: str,
    external_id: str,
    db: Session = Depends(get_db)
):
    """Get all conflicts for a specific external entity (e.g., Stripe customer)"""
    try:
        conflicts = conflict_repo.get_conflicts_by_external_id(db, external_system, external_id)
        conflicts_data = [conflict.model_dump() for conflict in conflicts]
        
        return response_handler.success(
            data={
                "conflicts": conflicts_data,
                "count": len(conflicts_data),
                "external_system": external_system,
                "external_id": external_id
            },
            message=f"Retrieved {len(conflicts_data)} conflicts for {external_system} ID {external_id}"
        )
        
    except Exception as e:
        return response_handler.failure(
            message=f"Failed to retrieve conflicts: {str(e)}",
            status_code=500
        )


@router.get("/strategies/available")
def get_available_strategies():
    """Get list of available conflict resolution strategies"""
    strategies = [
        {
            "value": strategy.value,
            "name": strategy.name.replace("_", " ").title(),
            "description": {
                "reject": "Reject the conflicting change and keep existing data",
                "merge": "Merge the external data with existing local data", 
                "flag": "Flag for manual review without automatic resolution",
                "auto_rename": "Automatically rename conflicting field to avoid collision"
            }.get(strategy.value, "")
        }
        for strategy in ConflictResolutionStrategy
    ]
    
    return response_handler.success(
        data=strategies,
        message="Retrieved available conflict resolution strategies"
    )