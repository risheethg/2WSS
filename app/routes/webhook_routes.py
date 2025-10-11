from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Dict, Any
import json

from app.core.config import settings
from app.core.database import get_db
from app.core.logger import logger
from app.integrations.registry import integration_registry
from app.integrations.base import InwardIntegrationService

router = APIRouter(
    prefix="/webhooks",
    tags=["Webhooks"]
)

def get_integration_webhook_secrets() -> Dict[str, str]:
    """Get webhook secrets for each integration."""
    return {
        "stripe": settings.STRIPE_WEBHOOK_SECRET,
    }

@router.post("/{integration_name}")
async def handle_webhook(
    integration_name: str,
    request: Request,
    db: Session = Depends(get_db),
    signature: str = Header(None, alias="stripe-signature"),
    x_hub_signature: str = Header(None),
    authorization: str = Header(None),
):
    """Generic webhook handler that routes events to integration services."""
    # Validate integration
    integration_service = integration_registry.get_integration(integration_name)
    if not integration_service:
        logger.error(f"Integration '{integration_name}' not found")
        raise HTTPException(status_code=404, detail="Integration not found")
    
    if not integration_service.is_enabled:
        logger.warning(f"Integration '{integration_name}' is disabled")
        raise HTTPException(status_code=503, detail="Integration is currently disabled")

    try:
        # Get the raw payload
        payload = await request.body()
        
        # Get the appropriate signature header based on integration
        webhook_signature = signature or x_hub_signature
        
        if not webhook_signature:
            logger.error(f"No signature header provided for {integration_name} webhook")
            raise HTTPException(status_code=400, detail="Missing signature header")

        # Get webhook secret for this integration
        webhook_secrets = get_integration_webhook_secrets()
        webhook_secret = webhook_secrets.get(integration_name)
        
        if not webhook_secret:
            logger.error(f"No webhook secret configured for integration '{integration_name}'")
            raise HTTPException(status_code=500, detail="Webhook secret not configured")

        # Verify webhook signature
        if not integration_service.verify_webhook_signature(payload, webhook_signature, webhook_secret):
            logger.error(f"Invalid signature for {integration_name} webhook")
            raise HTTPException(status_code=400, detail="Invalid signature")

        # Parse the event based on integration type
        event = await parse_webhook_event(integration_name, payload, webhook_signature, webhook_secret)
        
        if not event:
            logger.error(f"Failed to parse {integration_name} webhook event")
            raise HTTPException(status_code=400, detail="Invalid payload")

        # Extract event information
        event_type = event.get('type')
        event_data = event.get('data', {}).get('object', event.get('data', {}))
        
        logger.info(f"Received {integration_name} webhook event: {event_type}")

        # Delegate to the integration service
        success = integration_service.handle_webhook_event(event_type, event_data, db)
        
        if success:
            logger.info(f"Successfully processed {integration_name} webhook event: {event_type}")
            return {"status": "success", "message": f"{integration_name} webhook event processed"}
        else:
            # Log the failure but return 200 to prevent webhook retries for non-critical issues
            logger.warning(f"Failed to process {integration_name} webhook event: {event_type} - returning success to prevent retries")
            return {"status": "processed", "message": f"{integration_name} webhook event acknowledged but not processed"}

    except HTTPException:
        # Re-raise HTTP exceptions as they are already properly formatted
        raise
    except Exception as e:
        logger.error(f"Unexpected error processing {integration_name} webhook: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

async def parse_webhook_event(integration_name: str, payload: bytes, signature: str, secret: str) -> Dict[str, Any]:
    """Parse webhook event based on integration type."""
    try:
        if integration_name == "stripe":
            import stripe
            # Use Stripe's library for event validation
            event = stripe.Webhook.construct_event(payload, signature, secret)
            return event
        else:
            # Parse JSON for other integrations
            return json.loads(payload.decode('utf-8'))
            
    except Exception as e:
        logger.error(f"Error parsing {integration_name} webhook event: {e}")
        return None

# Legacy Stripe endpoint for backward compatibility
@router.post("/stripe")
async def stripe_webhook_legacy(
    request: Request,
    stripe_signature: str = Header(None),
    db: Session = Depends(get_db)
):
    """Legacy Stripe webhook endpoint - redirects to generic handler."""
    return await handle_webhook(
        integration_name="stripe",
        request=request,
        db=db,
        signature=stripe_signature
    )