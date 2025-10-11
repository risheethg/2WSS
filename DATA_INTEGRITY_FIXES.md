# Data Consistency & Integrity Fixes

## 🎯 Overview

This implementation addresses all **CRITICAL** data consistency and integrity edge cases identified in the Zenskar two-way integration system:

1. **Race conditions between webhook and API operations**
2. **Customer created locally but Stripe creation fails** 
3. **Duplicate email entries across integrations**
4. **Integration ID mismatches between systems**
5. **Partial sync failures leaving inconsistent state**
6. **Transaction rollback failures**
7. **Orphaned integration records**

## 🔧 Integration Approach

**Enhanced functionality has been integrated directly into existing files** to maintain backward compatibility and reduce code duplication:

- **Enhanced `app/services/customer_service.py`** - Added integrity-protected methods alongside existing ones
- **Enhanced `app/routes/customer_routes.py`** - Added optional integrity protection via headers
- **New supporting services** - Added as separate modules for specific functionality

## 🏗️ Architecture Components

### 1. Database-Level Constraints (`3c4d5e6f7g8h_add_data_integrity_constraints.py`)
- **Unique constraints** on integration IDs
- **Composite indexes** for performance
- **Foreign key constraints** with CASCADE DELETE
- **Integration sync state table** for tracking
- **Idempotency keys table** for deduplication

### 2. Distributed Locking (`app/core/locking.py`)
- **Redis-based distributed locks** (with in-memory fallback)
- **Customer-specific locks** to prevent concurrent modifications
- **Email-based locks** to prevent duplicate account creation
- **Integration-specific locks** for external operations
- **Timeout handling** and **deadlock prevention**

### 3. Idempotency Service (`app/core/idempotency.py`)
- **Idempotency keys** for safe operation retries
- **Request hashing** to detect true duplicates vs conflicts
- **Status tracking** (processing, completed, failed)
- **Automatic cleanup** of expired keys
- **Decorator support** for easy function wrapping

### 4. Transaction Coordinator (`app/core/transactions.py`)
- **Saga pattern** implementation for distributed transactions
- **Compensating actions** for rollback scenarios
- **Step-by-step execution** with retry logic
- **Automatic compensation** on failures
- **Transaction state tracking**

### 5. Integration State Tracking (`app/services/sync_service.py`)
- **Sync state management** per customer per integration
- **Orphaned record detection** and cleanup
- **Retry logic** for failed synchronizations
- **Health monitoring** and statistics
- **Automated maintenance** tasks

### 6. Enhanced Customer Service (`app/services/enhanced_customer_service.py`)
- **Combines all integrity mechanisms** into unified service
- **Async/await support** for distributed operations
- **Comprehensive error handling** with proper rollbacks
- **Integration health monitoring**
- **Data consistency validation** and repair

## 🚀 Usage

### Enhanced API Endpoints (Integrated into existing /customers routes)

```bash
# Create customer with optional integrity protection
POST /customers/
Headers: 
  Idempotency-Key: unique-operation-id (optional)
  X-Use-Integrity-Protection: true (optional, default: false)
  Content-Type: application/json
Body: {"name": "John Doe", "email": "john@example.com"}

# Update customer with optional integrity protection  
PUT /customers/{id}
Headers: 
  Idempotency-Key: unique-operation-id (optional)
  X-Use-Integrity-Protection: true (optional)

# Delete customer with optional integrity protection
DELETE /customers/{id}
Headers: 
  Idempotency-Key: unique-operation-id (optional)
  X-Use-Integrity-Protection: true (optional)

# Check customer sync health across integrations
GET /customers/{id}/sync-health

# Check integration health statistics  
GET /customers/integration-health/{integration_name}

# Retry failed synchronizations
POST /customers/retry-failed-syncs?integration_name=stripe

# Clean up orphaned records
POST /customers/cleanup-orphaned?integration_name=stripe

# Validate data consistency
GET /customers/data-consistency/validate

# Fix data consistency issues
POST /customers/data-consistency/fix
```

### Backward Compatibility

The existing endpoints work exactly as before:
```bash
# Legacy mode (default behavior)
POST /customers/
Body: {"name": "John Doe", "email": "john@example.com"}

# Enhanced mode (opt-in via header)
POST /customers/  
Headers: X-Use-Integrity-Protection: true
Body: {"name": "John Doe", "email": "john@example.com"}
```

### Programmatic Usage

```python
from app.services.customer_service import customer_service
from app.models.customer import CustomerCreate

# Legacy mode (backward compatible)
customer = CustomerCreate(name="John Doe", email="john@example.com")
result = customer_service.create_customer(db, customer)

# Enhanced mode with full integrity protection
customer = CustomerCreate(name="John Doe", email="john@example.com")  
result = await customer_service.create_customer_with_integrity(
    db, customer, idempotency_key="create-john-doe-001"
)

# The enhanced service automatically handles:
# - Distributed locking to prevent race conditions
# - Idempotency to prevent duplicate operations  
# - Transaction coordination with rollback
# - Integration state tracking
# - Error handling with retry logic
```

## 🔧 How It Solves Each Edge Case

### 1. Race Conditions Between Webhook and API Operations
- **Solution**: Distributed locking on customer ID and email
- **Mechanism**: Redis-based locks with timeout protection
- **Result**: Only one process can modify a customer at a time

### 2. Customer Created Locally but Stripe Creation Fails  
- **Solution**: Distributed transactions with compensating actions
- **Mechanism**: Saga pattern with automatic rollback
- **Result**: Failed external operations trigger local rollback

### 3. Duplicate Email Entries Across Integrations
- **Solution**: Email-based distributed locks + validation
- **Mechanism**: Lock on normalized email during operations
- **Result**: Prevents concurrent creation of same email

### 4. Integration ID Mismatches Between Systems
- **Solution**: Integration sync state tracking
- **Mechanism**: Dedicated table tracking external IDs per integration
- **Result**: Consistent mapping between local and external IDs

### 5. Partial Sync Failures Leaving Inconsistent State
- **Solution**: Transaction coordinator with step-by-step rollback
- **Mechanism**: Execute operations as atomic transactions
- **Result**: Either all operations succeed or all are rolled back

### 6. Transaction Rollback Failures
- **Solution**: Robust compensating transaction system
- **Mechanism**: Pre-defined rollback functions for each operation type
- **Result**: Guaranteed cleanup even when primary rollback fails

### 7. Orphaned Integration Records
- **Solution**: Sync state tracking + automated cleanup
- **Mechanism**: Track all external records and their lifecycle
- **Result**: Orphaned records are detected and cleaned up

## 🛡️ Safety Features

### Idempotency Protection
- **Safe retries**: Operations can be retried without side effects
- **Duplicate detection**: Same operation with same data returns cached result
- **Conflict prevention**: Different data with same key raises error

### Distributed Locking
- **Deadlock prevention**: Timeout-based lock acquisition
- **Automatic cleanup**: Locks expire automatically
- **Fallback support**: In-memory locks when Redis unavailable

### Transaction Safety  
- **Atomic operations**: All-or-nothing execution
- **Compensation guarantees**: Failed operations trigger automatic cleanup
- **State tracking**: Full audit trail of operation attempts

### Data Validation
- **Email uniqueness**: Enforced across active customers
- **Integration consistency**: Verified before operations
- **Constraint validation**: Database-level integrity checks

## 📊 Monitoring & Maintenance

### Health Endpoints
- **Customer sync health**: Check sync status per customer
- **Integration health**: Statistics and failure rates per integration
- **Data consistency validation**: Detect and report integrity issues

### Automated Maintenance
- **Failed sync retry**: Automatically retry failed operations
- **Orphaned record cleanup**: Remove abandoned external records
- **Expired key cleanup**: Clean up old idempotency keys
- **Consistency repair**: Fix detected data integrity issues

## 🔄 Migration Steps

1. **Run the database migration**:
   ```bash
   alembic upgrade head
   ```

2. **Configure Redis** (optional, falls back to in-memory locks)

3. **Deploy the enhanced functionality** (backward compatible)

4. **Gradually opt-in** to enhanced mode by setting `X-Use-Integrity-Protection: true` header

5. **Monitor health endpoints** for any issues

6. **Use new monitoring endpoints** for operational visibility

## 🎉 Benefits

✅ **Eliminates race conditions** between concurrent operations  
✅ **Prevents data inconsistencies** across system boundaries  
✅ **Enables safe retries** of failed operations  
✅ **Provides automatic recovery** from partial failures  
✅ **Maintains audit trail** of all synchronization attempts  
✅ **Supports operational maintenance** with health monitoring  
✅ **Ensures data integrity** at both application and database levels  

The implementation provides **enterprise-grade reliability** for the two-way integration system while maintaining backward compatibility and operational simplicity.