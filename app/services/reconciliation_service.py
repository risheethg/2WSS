import logging
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
import stripe
from app.models.customer import Customer
from app.models.reconciliation import ReconciliationReport, DataMismatch, ReconciliationSummary
from app.repos.reconciliation_repo import ReconciliationRepository, DataMismatchRepository
from app.repos.customer_repo import customer_repo
from app.integrations.stripe_service import StripeIntegration
from app.core.config import get_settings

logger = logging.getLogger(__name__)


class ReconciliationService:
    def __init__(self, db: Session):
        self.db = db
        self.reconciliation_repo = ReconciliationRepository(db)
        self.mismatch_repo = DataMismatchRepository(db)
        # Use the global customer_repo instance
        self.customer_repo = customer_repo
        self.stripe_service = StripeIntegration()
        self.settings = get_settings()
    
    async def run_reconciliation(self, auto_resolve: bool = False) -> ReconciliationReport:
        """
        Run a complete reconciliation between local customers and Stripe customers.
        
        Args:
            auto_resolve: If True, automatically resolve simple mismatches
        """
        logger.info("Starting customer data reconciliation")
        
        # Create report
        report = self.reconciliation_repo.create_report()
        
        try:
            # Get all customers from both systems
            local_customers = await self._get_local_customers()
            stripe_customers = await self._get_stripe_customers()
            
            # Update report counts
            report.total_local_customers = len(local_customers)
            report.total_stripe_customers = len(stripe_customers)
            
            logger.info(f"Found {len(local_customers)} local customers, {len(stripe_customers)} Stripe customers")
            
            # Create lookup dictionaries
            local_by_email = {c.email: c for c in local_customers}
            local_by_stripe_id = {c.stripe_customer_id: c for c in local_customers if c.stripe_customer_id}
            stripe_by_email = {c['email']: c for c in stripe_customers if c.get('email')}
            stripe_by_id = {c['id']: c for c in stripe_customers}
            
            mismatches = []
            
            # Check for customers in local but not in Stripe (or mismatched)
            for local_customer in local_customers:
                await self._check_local_customer(
                    local_customer, stripe_by_email, stripe_by_id, report.id, mismatches, auto_resolve
                )
            
            # Check for customers in Stripe but not in local
            for stripe_customer in stripe_customers:
                await self._check_stripe_customer(
                    stripe_customer, local_by_email, local_by_stripe_id, report.id, mismatches
                )
            
            # Update report
            report.mismatches_found = len(mismatches)
            report.auto_resolved = sum(1 for m in mismatches if m.resolution_status == "auto_resolved")
            report.manual_review_needed = sum(1 for m in mismatches if m.resolution_status == "pending")
            report.status = "completed"
            report.completed_at = datetime.utcnow()
            
            self.db.commit()
            
            logger.info(f"Reconciliation completed: {report.mismatches_found} mismatches, {report.auto_resolved} auto-resolved")
            
            return report
            
        except Exception as e:
            logger.error(f"Reconciliation failed: {str(e)}")
            report.status = "failed"
            report.error_message = str(e)
            report.completed_at = datetime.utcnow()
            self.db.commit()
            raise
    
    async def _get_local_customers(self) -> List[Customer]:
        """Get all active local customers."""
        # Get all active customers using the customer_repo interface
        filters = {"is_active": True}
        return self.customer_repo.get_all(self.db, skip=0, limit=10000, filters=filters)
    
    async def _get_stripe_customers(self) -> List[Dict[str, Any]]:
        """Get all customers from Stripe."""
        try:
            customers = []
            # Stripe pagination - get all customers
            starting_after = None
            
            while True:
                params = {"limit": 100}
                if starting_after:
                    params["starting_after"] = starting_after
                
                response = stripe.Customer.list(**params)
                customers.extend(response.data)
                
                if not response.has_more:
                    break
                    
                starting_after = response.data[-1].id
            
            # Convert to dict format for easier handling
            return [self._stripe_customer_to_dict(c) for c in customers]
            
        except Exception as e:
            logger.error(f"Failed to fetch Stripe customers: {str(e)}")
            raise
    
    def _stripe_customer_to_dict(self, stripe_customer) -> Dict[str, Any]:
        """Convert Stripe customer object to dictionary."""
        return {
            'id': stripe_customer.id,
            'email': stripe_customer.email,
            'name': stripe_customer.name,
            'created': stripe_customer.created,
            'metadata': dict(stripe_customer.metadata) if stripe_customer.metadata else {}
        }
    
    async def _check_local_customer(self, local_customer: Customer, 
                                  stripe_by_email: Dict, stripe_by_id: Dict, 
                                  report_id: int, mismatches: List, auto_resolve: bool):
        """Check a local customer against Stripe data."""
        
        # Case 1: Local customer has Stripe ID - check if it exists and matches
        if local_customer.stripe_customer_id:
            stripe_customer = stripe_by_id.get(local_customer.stripe_customer_id)
            
            if not stripe_customer:
                # Stripe customer was deleted or ID is invalid
                mismatch = self.mismatch_repo.create_mismatch(
                    report_id=report_id,
                    customer_id=local_customer.id,
                    stripe_customer_id=local_customer.stripe_customer_id,
                    email=local_customer.email,
                    mismatch_type="missing_in_stripe",
                    resolution_status="pending"
                )
                mismatches.append(mismatch)
                return
            
            # Check field mismatches
            await self._compare_customer_fields(
                local_customer, stripe_customer, report_id, mismatches, auto_resolve
            )
        
        # Case 2: Local customer has no Stripe ID - try to find by email
        else:
            stripe_customer = stripe_by_email.get(local_customer.email)
            
            if stripe_customer:
                # Found matching customer in Stripe, but local doesn't have the ID
                mismatch = self.mismatch_repo.create_mismatch(
                    report_id=report_id,
                    customer_id=local_customer.id,
                    stripe_customer_id=stripe_customer['id'],
                    email=local_customer.email,
                    mismatch_type="field_mismatch",
                    field_name="stripe_customer_id",
                    local_value="None",
                    stripe_value=stripe_customer['id'],
                    resolution_status="auto_resolved" if auto_resolve else "pending",
                    resolution_action="Update local customer with Stripe ID" if auto_resolve else None
                )
                
                if auto_resolve:
                    # Auto-resolve by updating local customer
                    local_customer.stripe_customer_id = stripe_customer['id']
                    self.db.commit()
                    mismatch.resolved_at = datetime.utcnow()
                    self.db.commit()
                
                mismatches.append(mismatch)
            else:
                # Customer exists locally but not in Stripe
                mismatch = self.mismatch_repo.create_mismatch(
                    report_id=report_id,
                    customer_id=local_customer.id,
                    email=local_customer.email,
                    mismatch_type="missing_in_stripe",
                    resolution_status="pending"
                )
                mismatches.append(mismatch)
    
    async def _check_stripe_customer(self, stripe_customer: Dict, 
                                   local_by_email: Dict, local_by_stripe_id: Dict, 
                                   report_id: int, mismatches: List):
        """Check a Stripe customer against local data."""
        
        # Check if this Stripe customer exists locally
        local_customer = local_by_stripe_id.get(stripe_customer['id'])
        
        if not local_customer and stripe_customer.get('email'):
            # Try to find by email
            local_customer = local_by_email.get(stripe_customer['email'])
        
        if not local_customer:
            # Customer exists in Stripe but not locally
            mismatch = self.mismatch_repo.create_mismatch(
                report_id=report_id,
                stripe_customer_id=stripe_customer['id'],
                email=stripe_customer.get('email', 'unknown'),
                mismatch_type="missing_in_local",
                resolution_status="pending"
            )
            mismatches.append(mismatch)
    
    async def _compare_customer_fields(self, local_customer: Customer, stripe_customer: Dict,
                                     report_id: int, mismatches: List, auto_resolve: bool):
        """Compare individual fields between local and Stripe customers."""
        
        # Compare name
        if local_customer.name != stripe_customer.get('name'):
            mismatch = self.mismatch_repo.create_mismatch(
                report_id=report_id,
                customer_id=local_customer.id,
                stripe_customer_id=stripe_customer['id'],
                email=local_customer.email,
                mismatch_type="field_mismatch",
                field_name="name",
                local_value=local_customer.name,
                stripe_value=stripe_customer.get('name'),
                resolution_status="pending"  # Name mismatches usually need manual review
            )
            mismatches.append(mismatch)
        
        # Compare email
        if local_customer.email != stripe_customer.get('email'):
            mismatch = self.mismatch_repo.create_mismatch(
                report_id=report_id,
                customer_id=local_customer.id,
                stripe_customer_id=stripe_customer['id'],
                email=local_customer.email,
                mismatch_type="field_mismatch",
                field_name="email",
                local_value=local_customer.email,
                stripe_value=stripe_customer.get('email'),
                resolution_status="pending"  # Email mismatches need careful review
            )
            mismatches.append(mismatch)
    
    async def get_reconciliation_summary(self, report_id: int) -> Optional[ReconciliationSummary]:
        """Get a complete summary of a reconciliation report."""
        report = self.reconciliation_repo.get_report_with_mismatches(report_id)
        if not report:
            return None
        
        mismatches = self.mismatch_repo.get_by_report_id(report_id)
        
        from app.models.reconciliation import ReconciliationReportResponse, DataMismatchResponse
        
        return ReconciliationSummary(
            report=ReconciliationReportResponse.from_orm(report),
            mismatches=[DataMismatchResponse.from_orm(m) for m in mismatches]
        )
    
    async def get_latest_reports(self, limit: int = 10) -> List[ReconciliationReport]:
        """Get the most recent reconciliation reports."""
        return self.reconciliation_repo.get_latest_reports(limit)
    
    async def resolve_mismatch(self, mismatch_id: int, action: str) -> Optional[DataMismatch]:
        """Manually resolve a data mismatch."""
        return self.mismatch_repo.resolve_mismatch(mismatch_id, action)