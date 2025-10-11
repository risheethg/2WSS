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