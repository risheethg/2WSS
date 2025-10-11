from fastapi import APIRouter, Request, Header, HTTPException, Depends
from sqlalchemy.orm import Session
import stripe

from app.core.config import settings
from app.core.database import get_db
from app.services.customer_service import customer_service

router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"]
)

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: Session = Depends(get_db)
):
    try:
        payload = await request.body()
        event = stripe.Webhook.construct_event(
            payload=payload,
            sig_header=stripe_signature,
            secret=settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    event_type = event['type']
    stripe_customer_data = event['data']['object']
    print(f"Received Stripe event: {event_type}")

    if event_type in ['customer.created', 'customer.updated']:
        customer_service.handle_stripe_customer_upsert(db, stripe_customer_data)
    elif event_type == 'customer.deleted':
        customer_service.handle_stripe_customer_deleted(db, stripe_customer_data)
    
    return {"status": "success"}