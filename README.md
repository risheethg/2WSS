# Two-Way Integration Service

A production-ready, scalable two-way integration service that synchronizes customer data between your application and external services (Stripe, Salesforce, etc.) with comprehensive error handling, conflict resolution, and monitoring capabilities.

## Table of Contents

- [Overview](#overview)
- [Tech Stack](#tech-stack)
- [System Architecture](#system-architecture)
- [Features](#features)
- [Prerequisites](#prerequisites)
- [Quick Setup](#quick-setup)
- [Environment Configuration](#environment-configuration)
- [API Documentation](#api-documentation)
- [Edge Cases & Resilience](#edge-cases--resilience)
- [Code Structure](#code-structure)
- [Monitoring & Admin](#monitoring--admin)
- [Deployment](#deployment)
- [Extensibility](#extensibility)
- [Troubleshooting](#troubleshooting)

## Overview

This service implements a **bi-directional, real-time synchronization system** between your customer catalog and external service providers. Built with enterprise-grade reliability patterns, it ensures data consistency across distributed systems while handling common edge cases like network failures, duplicate events, and data conflicts.

### Key Capabilities

- **Real-time bi-directional sync** between local database and external services
- **Event-driven architecture** with Kafka for reliable message processing
- **Comprehensive error handling** with retry mechanisms and dead letter queues
- **Data conflict resolution** with configurable strategies
- **Extensible plugin architecture** for adding new integrations
- **Production monitoring** with admin interfaces and reconciliation tools

## Tech Stack

### Core Technologies
- **Backend Framework**: FastAPI (Python 3.11+)
- **Database**: PostgreSQL 15 with Alembic migrations
- **Message Queue**: Apache Kafka with Zookeeper
- **Containerization**: Docker & Docker Compose
- **API Documentation**: OpenAPI/Swagger

### Integration Services
- **Stripe API**: Payment processing platform integration
- **Webhooks**: Real-time event processing from external services
- **Ngrok/Localtunnel**: Local webhook endpoint exposure (development)

### Architecture Patterns
- **Repository Pattern**: Clean data access abstraction
- **Service Layer**: Business logic encapsulation
- **Transactional Outbox**: Reliable event publishing
- **Circuit Breaker**: API failure resilience
- **Registry Pattern**: Pluggable integrations

## System Architecture

```
┌─────────────────────────────────────┐    ┌─────────────────┐
│            FastAPI App              │    │   PostgreSQL    │
│                                     │    │                 │
│  ┌─────────────┐  ┌─────────────┐   │    │ ┌─────────────┐ │
│  │ Customer    │  │ Admin       │   │◄───┤ │ Customers   │ │
│  │ Routes      │  │ Routes      │   │    │ │ Table       │ │
│  └─────────────┘  └─────────────┘   │    │ └─────────────┘ │
│                                     │    │                 │
│  ┌─────────────┐  ┌─────────────┐   │    │ ┌─────────────┐ │
│  │ Webhook     │  │ Customer    │   │    │ │ Outbox      │ │
│  │ Handler     │  │ Service     │   │    │ │ Events      │ │
│  └─────────────┘  └─────────────┘   │    │ └─────────────┘ │
│                                     │    │                 │
│  ┌─────────────┐  ┌─────────────┐   │    │ ┌─────────────┐ │
│  │ Conflict    │  │Reconciliation│   │    │ │ Conflicts/  │ │
│  │ Resolution  │  │ Service     │   │    │ │ Reports     │ │
│  └─────────────┘  └─────────────┘   │    │ └─────────────┘ │
└─────────────────────────────────────┘    └─────────────────┘
                     │                              ▲
                     │ Outbox                       │
                     ▼ Processing                   │
┌─────────────────────────────────────┐            │
│            Worker Process           │            │
│                                     │            │
│  ┌─────────────┐  ┌─────────────┐   │            │
│  │ Outbox      │  │ Integration │   │────────────┘
│  │ Processor   │  │ Registry    │   │
│  └─────────────┘  └─────────────┘   │
│                                     │
│         ┌─────────────┐             │
│         │ Kafka       │             │
│         │ Consumer    │             │
│         └─────────────┘             │
└─────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────┐
│         Message Infrastructure      │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │ Zookeeper   │  │   Kafka     │   │
│  │             │  │             │   │
│  │             │  │ ┌─────────┐ │   │
│  │             │◄─┤ │customer_│ │   │
│  │             │  │ │events   │ │   │
│  │             │  │ └─────────┘ │   │
│  │             │  │ ┌─────────┐ │   │
│  │             │  │ │ DLQ     │ │   │
│  │             │  │ │ Topic   │ │   │
│  │             │  │ └─────────┘ │   │
│  └─────────────┘  └─────────────┘   │
└─────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────┐
│         External Services           │
│                                     │
│  ┌─────────────┐  ┌─────────────┐   │
│  │ Stripe API  │  │ Future      │   │
│  │             │  │ Integration │   │
│  │ ┌─────────┐ │  │ (Salesforce,│   │
│  │ │Customer │ │  │  etc.)      │   │
│  │ │Webhooks │ │  │             │   │
│  │ └─────────┘ │  │             │   │
│  │      │      │  │             │   │
│  └──────┼──────┘  └─────────────┘   │
└─────────┼───────────────────────────┘
          │
          ▼ Webhooks sent back to FastAPI App
```

### Data Flow

**Outward Sync (Local → External Services):**
1. API request creates/updates customer via Customer Routes
2. Customer Service saves to database + adds event to outbox (same transaction)
3. Worker Process reads from outbox table and publishes to Kafka
4. Worker consumes from Kafka and calls Integration Registry
5. Integration Registry routes to appropriate service (Stripe, Salesforce, etc.)
6. External service processes request and may send confirmation webhook

**Inward Sync (External Services → Local):**
1. External service (e.g., Stripe) sends webhook to Webhook Handler
2. Webhook Handler calls Customer Service webhook-specific methods
3. Customer Service updates local database directly
4. No outbound event triggered (prevents circular updates)

**Background Processes:**
- **Reconciliation Service**: Periodically compares local vs external data
- **Conflict Resolution**: Manages data conflicts with admin intervention
- **Dead Letter Queue**: Handles permanently failed events

## Features

### Core Functionality
- **Customer CRUD Operations** with RESTful API
- **Real-time Stripe Integration** (create, update, delete)
- **Webhook Processing** for inbound Stripe events
- **Event-driven Architecture** with Kafka messaging
- **Database Migrations** with Alembic

### Advanced Features
- **Transactional Outbox Pattern** - Prevents event loss
- **Retry with Exponential Backoff** - Handles transient failures
- **Dead Letter Queue** - Manages permanently failed events
- **Idempotent Processing** - Safe to replay events
- **Conflict Resolution** - Handles data inconsistencies
- **Data Reconciliation** - Periodic drift detection
- **Circular Update Prevention** - Avoids infinite loops
- **Admin Interfaces** - Monitoring and manual intervention
- **Comprehensive Logging** - Structured logging throughout
- **Health Checks** - Container and service health monitoring
- **Configuration Management** - Environment-based settings
- **Error Tracking** - Detailed error reporting and metrics

## Prerequisites

### Required Software
- **Docker & Docker Compose** (v3.8+)
- **Python 3.11+** (for local development)
- **Git** for version control

### External Services
- **Stripe Test Account** (free at stripe.com)
- **Ngrok Account** (free at ngrok.com) for webhook development

### System Requirements
- **Memory**: 4GB+ RAM recommended
- **Storage**: 2GB+ free disk space
- **Network**: Internet access for API calls and webhooks

## Quick Setup

### 1. Clone Repository
```bash
git clone <repository-url>
cd Two-Way-Sync-Service
```

### 2. Environment Configuration
```bash
# Copy environment template
cp .env.template .env

# Edit .env with your configuration
nano .env
```

### 3. Start Services
```bash
# Start all services in background
docker-compose up -d

# Start services with logs (foreground)
docker-compose up

# Check service status
docker-compose ps

# View logs for all services
docker-compose logs -f

# View logs for specific service
docker-compose logs -f app
docker-compose logs -f worker
docker-compose logs -f kafka
```

### 4. Initialize Database
```bash
# Run migrations
docker-compose exec app alembic upgrade head

# Verify tables created
docker-compose exec db psql -U _user -d _db -c "\dt"
```

### 5. Test API
```bash
# Check API status
curl http://localhost:8000/

# Access API documentation
open http://localhost:8000/docs
```

### 6. Setup Webhooks (Development)
```bash
# Install ngrok
# Download from: https://ngrok.com/download

# Expose local webhook endpoint
ngrok http 8000

# Copy HTTPS URL and configure in Stripe Dashboard:
# Dashboard → Webhooks → Add endpoint
# URL: https://{your-ngrok-id}.ngrok.io/webhooks/stripe
# Events: customer.created, customer.updated, customer.deleted
```

## Environment Configuration

### Required Environment Variables

```bash
# Database Configuration
DATABASE_URL=postgresql://_user:_password@db:5432/_db

# Kafka Configuration
KAFKA_BOOTSTRAP_SERVERS=kafka:29092
KAFKA_CUSTOMER_TOPIC=customer_events
KAFKA_DLQ_TOPIC=customer_events_dlq

# Stripe Configuration
STRIPE_API_KEY=sk_test_...  # Your Stripe secret key
STRIPE_WEBHOOK_SECRET=whsec_...  # From Stripe webhook settings

# Integration Settings
STRIPE_INTEGRATION_ENABLED=true
SALESFORCE_INTEGRATION_ENABLED=false

# Retry Configuration
MAX_RETRY_ATTEMPTS=5
INITIAL_RETRY_DELAY=2
MAX_RETRY_DELAY=300

# Conflict Resolution
CONFLICT_RESOLUTION_STRATEGY=flag  # flag, reject, merge, auto_rename
AUTO_RESOLVE_CONFLICTS=false

# Reconciliation Settings
RECONCILIATION_HOUR=2          # 24-hour format
RECONCILIATION_MINUTE=0        # Minutes past the hour
RECONCILIATION_AUTO_RESOLVE=true

# Logging
LOGGER=INFO
```

### Optional Advanced Settings

```bash
# Performance Tuning
KAFKA_PARTITION_COUNT=3
KAFKA_REPLICATION_FACTOR=1
DB_POOL_SIZE=20

# Security
API_RATE_LIMIT=100
WEBHOOK_TIMEOUT=30

# Monitoring
ENABLE_METRICS=true
METRICS_PORT=9090
```

## API Documentation

### Customer Endpoints

#### Create Customer
```http
POST /customers/
Content-Type: application/json

{
    "name": "John Doe",
    "email": "john@example.com"
}

Response: 201 Created
{
    "status": "success",
    "message": "Customer created successfully",
    "data": {
        "id": 1,
        "name": "John Doe",
        "email": "john@example.com",
        "stripe_customer_id": "cus_...",
        "is_active": true
    }
}
```

#### Get All Customers
```http
GET /customers/?skip=0&limit=100

Response: 200 OK
{
    "status": "success",
    "data": [...]
}
```

#### Update Customer
```http
PUT /customers/{customer_id}
Content-Type: application/json

{
    "name": "John Smith",
    "email": "john.smith@example.com"
}
```

#### Delete Customer
```http
DELETE /customers/{customer_id}

Response: 200 OK
{
    "status": "success",
    "message": "Customer deleted successfully",
    "data": {
        "customer_id": 1,
        "deleted": true
    }
}
```

### Webhook Endpoints

#### Stripe Webhook
```http
POST /webhooks/stripe
Headers:
  - Stripe-Signature: {stripe_signature}
Content-Type: application/json

# Automatically processes:
# - customer.created
# - customer.updated  
# - customer.deleted
```

### Admin Endpoints

#### Conflict Management
```http
# Get all conflicts
GET /admin/conflicts/

# Get conflict statistics
GET /admin/conflicts/stats

# Resolve conflict
POST /admin/conflicts/{conflict_id}/resolve
{
    "resolution": "accept_local"  # accept_local, accept_remote, manual_merge
}
```

#### Reconciliation Management
```http
# Trigger manual reconciliation
POST /admin/reconciliation/run?auto_resolve=true

# Get reconciliation reports
GET /admin/reconciliation/reports

# Get specific report
GET /admin/reconciliation/reports/{report_id}

# Resolve data mismatch
POST /admin/reconciliation/mismatches/{mismatch_id}/resolve
{
    "resolution_action": "Updated customer name in Stripe to match local"
}
```

## Edge Cases & Resilience

### Outward Sync Failures (Our App → Stripe)

#### 1. Transactional Outbox Pattern
**Problem**: Events lost between database commit and Kafka publish
```python
# Problematic approach
def create_customer(customer_data):
    customer = save_to_db(customer_data)      # Could succeed
    publish_to_kafka(customer)                # Could fail - event lost!
    
# Our solution  
def create_customer(customer_data):
    with database_transaction():
        customer = save_to_db(customer_data)
        add_to_outbox(customer_event)         # Same transaction
    # Separate process publishes from outbox → Kafka
```

#### 2. Retry with Exponential Backoff
**Problem**: Transient API failures cause permanent data loss
```python
@retry_with_backoff(
    max_attempts=5,
    initial_delay=2,
    max_delay=300,
    exponential_base=2
)
def sync_to_stripe(customer_data):
    # Intelligent retry for: network timeouts, 429 rate limits, 5xx errors
    # No retry for: 4xx client errors, invalid data
    pass
```

#### 3. Message Ordering with Partition Keys
**Problem**: Updates processed out of order
```python
# Events for same customer always go to same partition
kafka_partition_key = f"customer_{customer.id}"
```

#### 4. Dead Letter Queue (DLQ)
**Problem**: Some events permanently fail after all retries
```python
# After max retries, move to DLQ for manual investigation
# Prevents blocking of other events
```

### Inward Sync Failures (Stripe → Our App)

#### 1. Idempotent Webhook Processing
**Problem**: Duplicate webhook deliveries create duplicate records
```python
def handle_customer_webhook(stripe_customer):
    # Check if already processed by Stripe ID
    existing = get_by_stripe_id(stripe_customer.id)
    if existing:
        return update_existing(existing, stripe_customer)  # Safe to repeat
    else:
        return create_new(stripe_customer)
```

#### 2. Out-of-Order Event Handling
**Problem**: customer.updated arrives before customer.created
```python
def handle_customer_created(stripe_customer):
    # Check if customer already exists locally (by email)
    local_customer = get_by_email(stripe_customer.email)
    if local_customer:
        # Link existing customer to Stripe ID
        link_to_stripe(local_customer, stripe_customer.id)
    else:
        # Create new customer
        create_from_stripe(stripe_customer)
```

#### 3. Data Conflict Resolution
**Problem**: Same email exists in multiple records
```python
class ConflictStrategy:
    FLAG = "flag"        # Mark conflict for manual review
    REJECT = "reject"    # Reject conflicting update
    MERGE = "merge"      # Intelligent field-level merge
    AUTO_RENAME = "auto_rename"  # Append suffix to resolve
    
# Configurable per organization's business rules
```

### General System Resilience

#### 1. Data Drift Reconciliation
**Problem**: Systems drift out of sync over time
```python
# Scheduled nightly job
def reconcile_customer_data():
    stripe_customers = fetch_all_stripe_customers()
    local_customers = fetch_all_local_customers()
    
    for customer in compare_field_by_field(stripe_customers, local_customers):
        if customer.has_mismatch():
            log_mismatch(customer.differences)
            if auto_resolve_enabled():
                resolve_simple_mismatches(customer)
```

#### 2. Circular Update Prevention  
**Problem**: Webhook triggers update, which triggers webhook, infinite loop
```python
# Separate methods for API vs Webhook updates
def update_customer(data):
    # Regular update - DOES trigger outbound events
    
def update_customer_from_webhook(data):  
    # Webhook update - NO outbound events (prevents loops)
```

#### 3. Circuit Breaker Pattern
**Problem**: Cascading failures when external service is down
```python
@circuit_breaker(failure_threshold=5, recovery_timeout=60)
def call_stripe_api():
    # Fails fast when Stripe is down
    # Prevents resource exhaustion
    pass
```

## Code Structure

```
├── app/
│   ├── core/                    # Core infrastructure
│   │   ├── config.py           # Environment configuration
│   │   ├── database.py         # Database connection & session
│   │   ├── messaging.py        # Kafka publisher/consumer
│   │   ├── logger.py           # Structured logging
│   │   ├── retry.py            # Retry mechanisms
│   │   └── response.py         # Standardized API responses
│   │
│   ├── models/                  # Database & API models
│   │   ├── customer.py         # Customer entity models
│   │   ├── outbox.py           # Outbox pattern models
│   │   ├── conflict.py         # Conflict tracking models
│   │   └── reconciliation.py   # Reconciliation models
│   │
│   ├── repos/                   # Data access layer
│   │   ├── base.py             # Abstract repository pattern
│   │   ├── customer_repo.py    # Customer data operations
│   │   ├── outbox_repo.py      # Outbox event operations
│   │   ├── conflict_repo.py    # Conflict data operations
│   │   └── reconciliation_repo.py # Reconciliation data
│   │
│   ├── services/                # Business logic layer
│   │   ├── customer_service.py # Customer business logic
│   │   ├── conflict_service.py # Conflict resolution logic
│   │   ├── reconciliation_service.py # Data reconciliation
│   │   ├── outbox_processor.py # Outbox event processing
│   │   └── universal_service.py # Cross-cutting concerns
│   │
│   ├── integrations/            # External service integrations
│   │   ├── base.py             # Abstract integration classes
│   │   ├── registry.py         # Integration plugin registry
│   │   ├── stripe_service.py   # Stripe API integration
│   │   └── __init__.py
│   │
│   └── routes/                  # API route handlers
│       ├── customer_routes.py  # Customer CRUD endpoints
│       ├── webhook_routes.py   # Webhook processing endpoints
│       ├── admin_routes.py     # Admin/monitoring endpoints
│       ├── conflict_routes.py  # Conflict management API
│       ├── reconciliation_routes.py # Reconciliation API
│       └── debug_routes.py     # Development/debugging endpoints
│
├── alembic/                     # Database migrations
│   ├── versions/               # Migration files
│   └── env.py                  # Alembic configuration
│
├── logs/                        # Application logs
├── docker-compose.yaml          # Service orchestration
├── Dockerfile                   # Application container
├── requirements.txt             # Python dependencies
├── main.py                      # FastAPI application entry
├── worker.py                    # Background worker process
├── alembic.ini                  # Database migration config
└── .env                         # Environment variables
```

### Architecture Principles

#### Repository Pattern
```python
# Abstract base for all data operations
class BaseRepository(ABC):
    @abstractmethod
    def get_by_id(self, entity_id: int) -> Optional[T]:
        pass
    
# Concrete implementation
class CustomerRepository(BaseRepository):
    def get_by_stripe_id(self, stripe_id: str) -> Optional[Customer]:
        # Stripe-specific query
        pass
```

#### Service Layer Pattern
```python
# Business logic encapsulation
class CustomerService:
    def __init__(self, customer_repo: CustomerRepository):
        self.customer_repo = customer_repo
        
    def create_customer(self, customer_data: CustomerCreate) -> Customer:
        # Validation, business rules, event publishing
        pass
```

#### Integration Registry Pattern  
```python
# Pluggable integration architecture
class IntegrationRegistry:
    def register_integration(self, name: str, integration_class: Type):
        # Dynamic integration loading
        pass
        
    def get_enabled_integrations(self) -> List[Integration]:
        # Returns only enabled integrations
        pass
```

## Monitoring & Admin

### Health Checks
- **Database**: Connection and query performance
- **Kafka**: Producer/consumer connectivity  
- **Stripe API**: Authentication and rate limits
- **Worker Process**: Event processing metrics

### Monitoring Endpoints
```bash
# Detailed service status  
GET /admin/status

# Kafka topic statistics
GET /admin/kafka/stats

# Integration status
GET /admin/integrations/status
```

### Admin Interfaces

#### Conflict Management Dashboard
- View all data conflicts with detailed diff
- Bulk resolution operations
- Conflict trend analytics
- Resolution audit trail

#### Reconciliation Dashboard  
- Schedule/trigger manual reconciliation
- View reconciliation reports and trends
- Drill down into specific mismatches
- Bulk mismatch resolution

#### Event Monitoring
- Real-time event processing metrics
- Retry queue monitoring  
- Dead letter queue management
- Event replay capabilities

### Logging Strategy

```python
# Structured logging with correlation IDs
logger.info("Customer created", extra={
    "customer_id": customer.id,
    "stripe_id": customer.stripe_id,
    "operation": "create",
    "correlation_id": request.correlation_id
})
```

## Docker Operations

### Essential Docker Commands

#### Starting the Application
```bash
# Start all services in background
docker-compose up -d

# Start with real-time logs  
docker-compose up

# Start specific services
docker-compose up -d db kafka
docker-compose up app worker
```

#### Monitoring Services
```bash
# Check running services
docker-compose ps

# View all logs
docker-compose logs -f

# View specific service logs
docker-compose logs -f app
docker-compose logs -f worker
docker-compose logs -f kafka
docker-compose logs -f db

# Follow logs from last 100 lines
docker-compose logs --tail=100 -f app
```

#### Managing Services
```bash
# Stop all services
docker-compose down

# Stop and remove volumes (WARNING: deletes data)
docker-compose down -v

# Restart specific service
docker-compose restart app
docker-compose restart worker

# Rebuild and restart
docker-compose up --build app
```

#### Database Operations
```bash
# Run database migrations
docker-compose exec app alembic upgrade head

# Connect to database
docker-compose exec db psql -U _user -d _db

# View database tables
docker-compose exec db psql -U _user -d _db -c "\dt"

# Backup database
docker-compose exec db pg_dump -U _user _db > backup.sql
```

#### Kafka Operations
```bash
# List Kafka topics
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Create topic manually
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --create --topic test_topic --partitions 3 --replication-factor 1

# Consume messages from topic
docker-compose exec kafka kafka-console-consumer --bootstrap-server localhost:9092 --topic customer_events --from-beginning
```

#### Troubleshooting
```bash
# Check service health
docker-compose ps
docker-compose exec app curl http://localhost:8000/

# Enter container for debugging
docker-compose exec app bash
docker-compose exec worker bash

# Check container resource usage
docker stats $(docker-compose ps -q)

# View detailed service info
docker-compose exec app python -c "import sys; print(sys.version)"
docker-compose exec db pg_isready -U _user -d _db
```

## Deployment

### Production Deployment

#### Docker Compose (Simple)
```yaml
# docker-compose.prod.yml
version: '3.8'
services:
  app:
    image: your-registry/-integration:latest
    environment:
      - ENVIRONMENT=production
      - LOG_LEVEL=INFO
    restart: unless-stopped
```

#### Kubernetes (Scalable)
```yaml
# k8s-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: -integration
spec:
  replicas: 3
  selector:
    matchLabels:
      app: -integration
  template:
    spec:
      containers:
      - name: app
        image: your-registry/-integration:latest
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: database-secret
              key: url
```

### Environment-Specific Configuration

#### Development
```bash
# .env.dev
DEBUG=true
LOG_LEVEL=DEBUG
STRIPE_API_KEY=sk_test_...
DATABASE_URL=postgresql://localhost:5432/_dev
```

#### Staging
```bash  
# .env.staging
DEBUG=false
LOG_LEVEL=INFO
STRIPE_API_KEY=sk_test_...
DATABASE_URL=postgresql://staging-db:5432/_staging
```

#### Production
```bash
# .env.prod
DEBUG=false
LOG_LEVEL=WARNING
STRIPE_API_KEY=sk_live_...
DATABASE_URL=postgresql://prod-db:5432/_prod
```

### Security Considerations

- **API Keys**: Use environment variables, never commit to code
- **Database**: Connection pooling, prepared statements
- **Webhooks**: Signature verification for all incoming webhooks
- **Rate Limiting**: Implement API rate limits
- **Input Validation**: Strict validation on all inputs
- **HTTPS**: TLS for all external communications

## Extensibility

### Adding New Integrations

#### 1. Create Integration Service
```python
# app/integrations/salesforce_service.py
from .base import BaseIntegrationService

class SalesforceIntegration(BaseIntegrationService):
    def __init__(self, enabled: bool = True):
        super().__init__("salesforce", enabled)
        # Salesforce API setup
        
    def create_customer(self, customer_data: dict, db: Session):
        # Implement Salesforce customer creation
        pass
        
    def handle_webhook_event(self, event_type: str, payload: dict, db: Session):
        # Handle Salesforce webhook events
        pass
```

#### 2. Register Integration
```python
# app/integrations/registry.py
def initialize_integrations(self):
    # Existing Stripe registration
    self.register_integration("stripe", StripeIntegration, ...)
    
    # Add Salesforce registration
    self.register_integration(
        "salesforce", 
        SalesforceIntegration,
        enabled=settings.SALESFORCE_INTEGRATION_ENABLED
    )
```

#### 3. Add Configuration
```bash
# .env
SALESFORCE_INTEGRATION_ENABLED=true
SALESFORCE_API_KEY=your_salesforce_key
SALESFORCE_WEBHOOK_SECRET=your_webhook_secret
```

### Supporting New Entity Types

#### 1. Create Models
```python
# app/models/invoice.py
class Invoice(Base):
    __tablename__ = "invoices"
    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"))
    amount = Column(Numeric(10, 2))
    # ... other fields
```

#### 2. Create Repository
```python
# app/repos/invoice_repo.py  
class InvoiceRepository(BaseRepository):
    # Implement invoice-specific data operations
    pass
```

#### 3. Create Service
```python
# app/services/invoice_service.py
class InvoiceService:
    def create_invoice(self, invoice_data):
        # Business logic + event publishing
        pass
```

#### 4. Add to Integrations
```python
# Each integration can handle multiple entity types
class StripeIntegration(BaseIntegrationService):
    def create_customer(self, data, db): pass
    def create_invoice(self, data, db): pass  # New method
    def create_product(self, data, db): pass  # Future expansion
```

### Plugin Architecture Benefits

- **Loose Coupling**: Integrations don't depend on each other
- **Independent Deployment**: Enable/disable integrations without code changes
- **Easy Testing**: Mock individual integrations
- **Configuration-Driven**: Control via environment variables
- **Scalable**: Add unlimited integrations without architectural changes

## Troubleshooting

### Common Issues

#### 1. Webhook Signature Verification Failed
```bash
# Check webhook secret configuration
docker-compose logs app | grep "signature"

# Verify Stripe webhook configuration
# Dashboard → Webhooks → Select your endpoint → Signing secret
```

#### 2. Kafka Connection Issues
```bash
# Check Kafka service health
docker-compose ps kafka

# Verify topic creation
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 --list

# Check consumer lag
docker-compose exec kafka kafka-consumer-groups --bootstrap-server localhost:9092 --describe --group customer-sync-group
```

#### 3. Database Migration Errors
```bash
# Check current migration status
docker-compose exec app alembic current

# View migration history
docker-compose exec app alembic history

# Force migration (caution in production)
docker-compose exec app alembic upgrade head
```

#### 4. Stripe API Rate Limits
```bash
# Monitor rate limit headers in logs
docker-compose logs app | grep "rate.limit"

# Adjust retry configuration
# Increase INITIAL_RETRY_DELAY and MAX_RETRY_DELAY in .env
```

### Performance Optimization

#### Database Optimization
```sql
-- Add indexes for common queries
CREATE INDEX idx_customers_stripe_id ON customers(stripe_customer_id);
CREATE INDEX idx_customers_email ON customers(email);
CREATE INDEX idx_outbox_events_status ON outbox_events(status, created_at);
```

#### Kafka Optimization
```bash
# Increase partitions for higher throughput
docker-compose exec kafka kafka-topics --bootstrap-server localhost:9092 \
  --alter --topic customer_events --partitions 6
```

#### Application Optimization
```python
# Database connection pooling
DATABASE_POOL_SIZE=20
DATABASE_MAX_OVERFLOW=30

# Async processing
KAFKA_BATCH_SIZE=100
WEBHOOK_BATCH_PROCESSING=true
```

### Debug Mode

```bash
# Enable debug logging
LOG_LEVEL=DEBUG

# Enable SQL query logging
DB_ECHO=true

# Enable detailed error traces
DEBUG_MODE=true

# Restart services
docker-compose restart app
```

## Metrics & Monitoring

### Key Metrics to Monitor

- **Event Processing Rate**: Events/second through system
- **API Response Times**: p95, p99 latencies for customer operations
- **Integration Success Rate**: Success/failure ratio per integration
- **Webhook Processing Time**: Time to process inbound webhooks
- **Conflict Resolution Rate**: Automatic vs manual resolution ratio
- **Data Drift Detection**: Mismatches found during reconciliation

### Alerting Recommendations

- **Critical**: Database connection failures, Kafka unavailability
- **Warning**: High API error rates, increased conflict rates
- **Info**: Reconciliation completion, successful migrations

---

## Conclusion

This integration service provides a robust, scalable foundation for bi-directional data synchronization. Built with production-grade patterns and comprehensive error handling, it's ready for real-world deployment while remaining extensible for future integrations and entity types.

**Key Benefits:**
- **Production Ready**: Comprehensive error handling and monitoring
- **Highly Scalable**: Event-driven architecture with horizontal scaling
- **Extensible Design**: Plugin architecture for unlimited integrations
- **Data Consistency**: Advanced conflict resolution and reconciliation
- **Developer Friendly**: Comprehensive documentation and testing
