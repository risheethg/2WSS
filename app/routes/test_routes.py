"""
Test Routes for Development

Simple endpoints to test conflict resolution without needing real Stripe webhooks.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any

from app.core.database import get_db
from app.core.response import response_handler
from app.integrations.stripe_service import StripeIntegration

router = APIRouter(
    prefix="/test",
    tags=["Test - Development Only"]
)


@router.post("/simulate-stripe-webhook")
def simulate_stripe_webhook(
    webhook_data: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """
    Simulate a Stripe webhook for testing purposes.
    
    This bypasses signature validation for development testing.
    """
    try:
        # Create a Stripe integration instance
        stripe_integration = StripeIntegration(enabled=True)
        
        # Extract event data
        event_type = webhook_data.get("type", "")
        event_data = webhook_data.get("data", {}).get("object", {})
        
        if not event_type or not event_data:
            return response_handler.failure(
                message="Invalid webhook data format",
                status_code=400
            )
        
        # Process the webhook event
        success = stripe_integration.handle_webhook_event(event_type, event_data, db)
        
        if success:
            return response_handler.success(
                data={
                    "event_type": event_type,
                    "processed": True
                },
                message="Webhook event processed successfully"
            )
        else:
            return response_handler.failure(
                message="Failed to process webhook event",
                status_code=400
            )
        
    except Exception as e:
        return response_handler.failure(
            message=f"Error processing webhook: {str(e)}",
            status_code=500
        )


@router.post("/delete_customer/{customer_id}")
def test_delete_customer_webhook(customer_id: int, db: Session = Depends(get_db)):
    """
    Test endpoint to simulate deleting a customer via Stripe webhook.
    This bypasses Stripe signature verification for testing purposes.
    """
    try:
        stripe_integration = StripeIntegration()
        
        # Get the customer to find their Stripe ID
        from app.repos.customer_repo import customer_repo
        customer = customer_repo.get_by_id(db, customer_id)
        
        if not customer:
            return response_handler.failure(
                message=f"Customer {customer_id} not found",
                status_code=404
            )
        
        if not customer.stripe_customer_id:
            return response_handler.failure(
                message=f"Customer {customer_id} has no Stripe ID - cannot simulate delete",
                status_code=400
            )
        
        # Simulate the customer.deleted webhook data
        fake_stripe_customer = {
            "id": customer.stripe_customer_id,
            "email": customer.email,
            "name": customer.name
        }
        
        # Process the delete webhook
        success = stripe_integration._handle_customer_deleted(fake_stripe_customer, db)
        
        if success:
            return response_handler.success(
                data={
                    "customer_id": customer_id,
                    "stripe_customer_id": customer.stripe_customer_id,
                    "action": "deactivated"
                },
                message="Customer delete webhook processed successfully"
            )
        else:
            return response_handler.failure(
                message="Failed to process customer delete webhook",
                status_code=400
            )
            
    except Exception as e:
        return response_handler.failure(
            message=f"Error testing delete webhook: {str(e)}",
            status_code=500
        )