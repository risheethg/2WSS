"""
Conflict Resolution Service

Handles data conflicts that occur during webhook processing.
"""

from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.logger import logger
from app.repos.conflict_repo import conflict_repo
from app.repos.customer_repo import customer_repo
from app.models.conflict import ConflictCreate, ConflictResolutionStrategy
from app.models import customer as customer_model


class ConflictResolutionService:
    """Service for handling data conflicts during webhook processing"""

    def handle_email_conflict(self, db: Session, stripe_customer_data: Dict[str, Any], 
                            integrity_error: IntegrityError) -> Tuple[bool, Optional[str]]:
        """
        Handle email constraint violation conflicts.
        
        Returns: (success: bool, error_message: Optional[str])
        """
        stripe_id = stripe_customer_data.get("id")
        email = stripe_customer_data.get("email", "")
        name = stripe_customer_data.get("name", "")
        
        logger.warning(f"Email conflict detected for Stripe customer {stripe_id} with email {email}")
        
        try:
            # Find the existing customer with this email
            existing_customer = customer_repo.get_by_field(db, "email", email)
            
            # Create conflict record
            conflict_data = ConflictCreate(
                conflict_type="email_constraint",
                entity_type="customer", 
                external_system="stripe",
                external_id=stripe_id,
                conflict_field="email",
                conflict_value=email,
                existing_entity_id=existing_customer.id if existing_customer else None,
                webhook_event_data=stripe_customer_data,
                error_message=str(integrity_error)
            )
            
            # Check for duplicate conflicts
            similar_conflicts = conflict_repo.check_for_similar_conflicts(
                db, "email_constraint", "email", email, "stripe"
            )
            
            if similar_conflicts:
                logger.info(f"Similar conflict already exists for email {email}, skipping duplicate")
                return True, "Similar conflict already recorded"
            
            # Create the conflict record
            conflict_record = conflict_repo.create_conflict(db, conflict_data)
            
            # Apply resolution strategy
            strategy = settings.CONFLICT_RESOLUTION_STRATEGY.lower()
            
            if strategy == "reject":
                return self._reject_conflict(db, conflict_record.id, stripe_customer_data)
            elif strategy == "auto_rename":
                return self._auto_rename_conflict(db, conflict_record.id, stripe_customer_data, existing_customer)
            elif strategy == "merge" and settings.AUTO_RESOLVE_CONFLICTS:
                return self._merge_conflict(db, conflict_record.id, stripe_customer_data, existing_customer)
            else:  # strategy == "flag" or manual merge
                return self._flag_for_review(db, conflict_record.id)
                
        except Exception as e:
            logger.error(f"Error handling email conflict: {e}")
            return False, str(e)

    def _reject_conflict(self, db: Session, conflict_id: int, 
                        stripe_customer_data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Reject the conflicting change"""
        try:
            success = conflict_repo.resolve_conflict(
                db, conflict_id, ConflictResolutionStrategy.REJECT.value,
                resolved_by="auto", notes="Automatically rejected due to email conflict"
            )
            
            if success:
                logger.info(f"Rejected Stripe customer {stripe_customer_data.get('id')} due to email conflict")
                return True, "Change rejected due to email conflict"
            else:
                return False, "Failed to record rejection"
                
        except Exception as e:
            logger.error(f"Error rejecting conflict: {e}")
            return False, str(e)

    def _auto_rename_conflict(self, db: Session, conflict_id: int, 
                            stripe_customer_data: Dict[str, Any],
                            existing_customer) -> Tuple[bool, Optional[str]]:
        """Automatically rename email to avoid conflict"""
        try:
            original_email = stripe_customer_data.get("email", "")
            stripe_id = stripe_customer_data.get("id")
            name = stripe_customer_data.get("name", "")
            
            # Generate a unique email by appending stripe ID
            new_email = f"{original_email.split('@')[0]}+stripe_{stripe_id}@{original_email.split('@')[1]}"
            
            # Create customer with modified email
            customer_data = customer_model.CustomerCreate(name=name, email=new_email)
            new_customer = customer_repo.create_with_integration_id(
                db, customer_data, "stripe_customer_id", stripe_id
            )
            
            # Mark conflict as resolved
            notes = f"Auto-renamed email from {original_email} to {new_email} to avoid conflict"
            success = conflict_repo.resolve_conflict(
                db, conflict_id, ConflictResolutionStrategy.AUTO_RENAME.value,
                resolved_by="auto", notes=notes
            )
            
            logger.info(f"Auto-renamed email for Stripe customer {stripe_id}: {original_email} -> {new_email}")
            return True, f"Created customer with renamed email: {new_email}"
            
        except Exception as e:
            logger.error(f"Error auto-renaming conflict: {e}")
            return False, str(e)

    def _merge_conflict(self, db: Session, conflict_id: int,
                       stripe_customer_data: Dict[str, Any],
                       existing_customer) -> Tuple[bool, Optional[str]]:
        """Merge Stripe customer with existing local customer"""
        try:
            stripe_id = stripe_customer_data.get("id")
            
            if not existing_customer:
                return False, "Cannot merge: existing customer not found"
            
            # Link existing customer to Stripe
            if not existing_customer.stripe_customer_id:
                # Update existing customer to link with Stripe
                from app.models.customer import CustomerUpdate
                
                # Update name if Stripe has a name and local doesn't, or if explicitly different
                update_name = stripe_customer_data.get("name", existing_customer.name)
                
                update_data = CustomerUpdate(name=update_name, email=existing_customer.email)
                
                # Manually set stripe_customer_id since it's not in the update model
                db_customer = db.query(customer_model.Customer).filter(
                    customer_model.Customer.id == existing_customer.id
                ).first()
                
                if db_customer:
                    db_customer.name = update_name
                    db_customer.stripe_customer_id = stripe_id
                    db.commit()
                    
                    # Mark conflict as resolved
                    notes = f"Merged Stripe customer {stripe_id} with existing local customer {existing_customer.id}"
                    conflict_repo.resolve_conflict(
                        db, conflict_id, ConflictResolutionStrategy.MERGE.value,
                        resolved_by="auto", notes=notes
                    )
                    
                    logger.info(f"Merged Stripe customer {stripe_id} with local customer {existing_customer.id}")
                    return True, "Successfully merged with existing customer"
                else:
                    return False, "Failed to find customer for merge"
            else:
                return False, f"Existing customer already linked to Stripe ID: {existing_customer.stripe_customer_id}"
                
        except Exception as e:
            logger.error(f"Error merging conflict: {e}")
            return False, str(e)

    def _flag_for_review(self, db: Session, conflict_id: int) -> Tuple[bool, Optional[str]]:
        """Flag conflict for manual review"""
        logger.info(f"Flagged conflict {conflict_id} for manual review")
        return True, "Conflict flagged for manual review"

    def manually_resolve_conflict(self, db: Session, conflict_id: int, 
                                strategy: str, resolved_by: str = "admin",
                                notes: str = None) -> Tuple[bool, str]:
        """Manually resolve a conflict with specified strategy"""
        try:
            conflict = conflict_repo.get_conflict_by_id(db, conflict_id)
            if not conflict:
                return False, "Conflict not found"
            
            if conflict.status != "pending":
                return False, f"Conflict already {conflict.status}"
            
            webhook_data = conflict.get_webhook_data()
            
            if strategy == ConflictResolutionStrategy.MERGE.value:
                existing_customer = None
                if conflict.existing_entity_id:
                    existing_customer = customer_repo.get_by_id(db, conflict.existing_entity_id)
                
                success, message = self._merge_conflict(db, conflict_id, webhook_data, existing_customer)
                return success, message
                
            elif strategy == ConflictResolutionStrategy.AUTO_RENAME.value:
                existing_customer = None
                if conflict.existing_entity_id:
                    existing_customer = customer_repo.get_by_id(db, conflict.existing_entity_id)
                
                success, message = self._auto_rename_conflict(db, conflict_id, webhook_data, existing_customer)
                return success, message
                
            elif strategy == ConflictResolutionStrategy.REJECT.value:
                success = conflict_repo.resolve_conflict(
                    db, conflict_id, strategy, resolved_by, notes or "Manually rejected"
                )
                return success, "Conflict rejected" if success else "Failed to reject conflict"
            
            else:
                return False, f"Unknown strategy: {strategy}"
                
        except Exception as e:
            logger.error(f"Error manually resolving conflict {conflict_id}: {e}")
            return False, str(e)


# Global service instance
conflict_service = ConflictResolutionService()