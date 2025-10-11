from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.integrations.stripe_service import StripeIntegration
from app.repos.customer_repo import customer_repo

router = APIRouter(
    prefix="/debug",
    tags=["Debug - Development Only"]
)


@router.post("/test-delete-webhook/{customer_id}")
def test_delete_webhook(customer_id: int, db: Session = Depends(get_db)):
    """
    Debug endpoint to test delete webhook processing without Stripe signature verification.
    """
    try:
        # Get the customer
        customer = customer_repo.get_by_id(db, customer_id)
        
        if not customer:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        
        if not customer.stripe_customer_id:
            raise HTTPException(status_code=400, detail=f"Customer {customer_id} has no Stripe ID")
        
        print(f"🧪 BEFORE DELETE: Customer {customer_id} - Active: {customer.is_active}, Stripe ID: {customer.stripe_customer_id}")
        
        # Simulate Stripe customer data for delete webhook
        stripe_customer_data = {
            "id": customer.stripe_customer_id,
            "email": customer.email,
            "name": customer.name
        }
        
        # Create Stripe integration and call delete handler directly
        stripe_integration = StripeIntegration()
        success = stripe_integration._handle_customer_deleted(stripe_customer_data, db)
        
        # Check the customer after delete attempt
        customer_after = customer_repo.get_by_id(db, customer_id)
        
        result = {
            "customer_id": customer_id,
            "stripe_customer_id": customer.stripe_customer_id,
            "delete_success": success,
            "before_active": customer.is_active,
            "after_active": customer_after.is_active if customer_after else None,
            "after_exists": customer_after is not None
        }
        
        print(f"🧪 AFTER DELETE: Customer {customer_id} - Active: {customer_after.is_active if customer_after else 'N/A'}, Success: {success}")
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing delete webhook: {str(e)}")


@router.get("/customer-status/{customer_id}")
def get_customer_debug_status(customer_id: int, db: Session = Depends(get_db)):
    """Get detailed customer status for debugging."""
    customer = customer_repo.get_by_id(db, customer_id)
    
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
    
    return {
        "customer_id": customer_id,
        "name": customer.name,
        "email": customer.email,
        "is_active": customer.is_active,
        "stripe_customer_id": customer.stripe_customer_id,
        "exists": True
    }