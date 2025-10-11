#!/usr/bin/env python3
"""
Direct test of delete webhook functionality
"""

import sys
sys.path.append('/app')

from app.integrations.stripe_service import StripeIntegration
from app.core.database import SessionLocal
from app.repos.customer_repo import customer_repo

# Test data - simulate Stripe sending us a customer.deleted webhook
fake_stripe_customer = {
    "id": "cus_TDWcMdAJZq4TVv",  # The Stripe ID for customer 5
    "email": "inbound-delete@test.com", 
    "name": "Inbound Delete Test"
}

print("Testing inbound delete webhook processing...")

# Get database session
with SessionLocal() as db:
    # Check customer before deletion
    customer_before = customer_repo.get_by_id(db, 5)
    print(f"Customer 5 before delete: active={customer_before.is_active if customer_before else 'NOT_FOUND'}")
    
    # Process the delete webhook
    stripe_integration = StripeIntegration()
    success = stripe_integration._handle_customer_deleted(fake_stripe_customer, db)
    
    print(f"Delete webhook processing result: {success}")
    
    # Check customer after deletion
    customer_after = customer_repo.get_by_id(db, 5)
    print(f"Customer 5 after delete: active={customer_after.is_active if customer_after else 'NOT_FOUND'}")
    
    if customer_after and not customer_after.is_active:
        print("✅ SUCCESS: Customer was successfully deactivated by delete webhook!")
    else:
        print("❌ FAILED: Customer was not deactivated as expected")