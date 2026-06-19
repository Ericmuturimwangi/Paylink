# Paylink

A Django REST Framework payment processing backend that integrates M-Pesa (Daraja STK Push) and Paystack, with a double-entry ledger, settlement reconciliation, audit logs, and PDF receipts.

---

## Architecture

```
HTTP Request
    │
    ▼
views.py  ──►  services.py  ──►  models.py (Payment, AuditLog, LedgerEntry)
                    │
                    ├──►  mpesa.py / paystack.py  (provider adapters)
                    └──►  tasks.py  (Celery: confirm, reconcile, receipt)
```

**Key design decisions:**

- **State machine** — `PaymentStatus` transitions are enforced by `states.py`. A `paid` payment can never go back to any other state.
- **Idempotency** — every create request requires an `Idempotency-Key` header; duplicate keys return the existing payment.
- **Callback deduplication** — `WebhookEvent` has a unique constraint on `(provider, dedupe_key)` to prevent double-processing.
- **Append-only audit trail** — `AuditLog` and `LedgerEntry` raise `ValueError` on update or delete.
- **Double-entry ledger** — every money movement posts balanced debit/credit legs through `post_balanced()` in `ledger.py`.
- **Token caching** — M-Pesa OAuth tokens are cached at module level for 55 minutes to avoid Daraja rate limiting.

---

## Project Structure

```
config/
  settings.py        # Django settings, loads .env
  celery.py          # Celery app definition
  urls.py            # Root URL conf (prefixes all routes with /api/)

payments/
  models.py          # Payment, WebhookEvent, AuditLog, Receipt, SettlementRecord, LedgerEntry
  states.py          # PaymentStatus enum + transition guard
  base.py            # PaymentProvider ABC, ChargeRequest/Response, CallbackResult dataclasses
  mpesa.py           # M-Pesa Daraja STK Push provider
  paystack.py        # Paystack provider (webhook + HMAC verification)
  registry.py        # get_provider(name) factory
  services.py        # PaymentService: create_and_charge, handle_callback, apply_status
  tasks.py           # Celery tasks: confirm_payment, reconcile_stuck_payments, generate_receipt
  views.py           # DRF API views
  urls.py            # URL patterns
  serializers.py     # DRF serializers
  ledger.py          # post_balanced() double-entry helper
  reconciliation.py  # ReconciliationService: ingest, reconcile, summary
  receipts.py        # ReceiptService: PDF generation
  money.py           # Money dataclass (minor units ↔ major)
  adapters/          # Statement/settlement file parsers
    mpesa_statement.py
    paystack_settlement.py
    registry.py      # get_adapter(name) factory

payments/tests/      # pytest test suite
conftest.py          # Shared fixtures (db, JWT token, make_paid helper)
```

---

## Prerequisites

- Python 3.11+
- PostgreSQL (system install)
- Redis (system install, used as Celery broker)
- An M-Pesa Daraja sandbox app ([developer.safaricom.co.ke](https://developer.safaricom.co.ke))
- A Paystack account for the secret key
- [ngrok](https://ngrok.com) or similar tunnel for receiving M-Pesa callbacks locally

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone <repo-url> paylink
cd paylink
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Create the PostgreSQL database and user

```bash
sudo -u postgres psql <<'SQL'
CREATE USER paylink WITH PASSWORD 'paylink';
CREATE DATABASE paylink OWNER paylink;
ALTER USER paylink CREATEDB;
SQL
```

### 3. Create the `.env` file

```ini
# Database
DB_NAME=paylink
DB_USER=paylink
DB_PASSWORD=paylink
DB_HOST=127.0.0.1
DB_PORT=5432

# Redis / Celery
REDIS_URL=redis://127.0.0.1:6379/0

# M-Pesa Daraja (sandbox)
MPESA_SHORTCODE=174379
MPESA_PASSKEY=<your-passkey>
MPESA_CONSUMER_KEY=<your-consumer-key>
MPESA_CONSUMER_SECRET=<your-consumer-secret>
MPESA_CALLBACK_URL=https://<your-ngrok-subdomain>.ngrok-free.app/api/callbacks/mpesa/

# Paystack
PAYSTACK_SECRET_KEY=sk_test_<your-key>
```

> For local testing, start ngrok first: `ngrok http 8000` and update `MPESA_CALLBACK_URL` with the forwarding URL.

### 4. Apply migrations and create a superuser

```bash
python manage.py migrate
python manage.py createsuperuser
```

### 5. Obtain a JWT token

```bash
curl -s -X POST http://localhost:8000/api/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "yourpassword"}' | python -m json.tool
```

Copy the `access` token for use as `Bearer <token>` in all authenticated requests.

---

## Running the application

Open four terminal windows (all with `source venv/bin/activate`):

```bash
# 1. Django dev server
python manage.py runserver

# 2. Celery worker
celery -A config worker -l info

# 3. Celery beat scheduler (reconciles stuck payments every 5 minutes)
celery -A config beat -l info

# 4. ngrok tunnel (M-Pesa callbacks)
ngrok http 8000
```

---

## API Reference

All routes are prefixed with `/api/`. Authenticated endpoints require `Authorization: Bearer <jwt>`.

### Create a payment

```
POST /api/payments/
Authorization: Bearer <jwt>
Idempotency-Key: <unique-string>
Content-Type: application/json

{
  "provider": "mpesa",
  "amount": "10",
  "currency": "KES",
  "customer_phone": "0712345678",
  "description": "Order #123",
  "reference": "ORD-123"
}
```

**Response** `201`:
```json
{
  "id": "a5ee3b06-...",
  "status": "processing",
  "provider": "mpesa",
  "currency": "KES",
  "provider_receipt": "",
  "amount": "10"
}
```

### Get payment status

```
GET /api/payments/<uuid>/status/
Authorization: Bearer <jwt>
```

### Get payment audit trail

```
GET /api/payments/<uuid>/audit/
Authorization: Bearer <jwt>
```

Returns a chronological list of all events on the payment (created, STK initiated, callback received, status changed, etc.).

### Download receipt (PDF)

Only available when `status == "paid"`.

```
GET /api/payments/<uuid>/receipt/
Authorization: Bearer <jwt>
```

Returns `application/pdf` as an attachment.

### M-Pesa callback (called by Safaricom)

```
POST /api/callbacks/mpesa/
POST /api/webhooks/mpesa/   ← alias
```

No authentication. Expects the standard Daraja STK callback body. Returns `{"ResultCode": 0, "ResultDesc": "Accepted"}`.

### Paystack webhook (called by Paystack)

```
POST /api/callbacks/paystack/
POST /api/webhooks/paystack/  ← alias
```

No authentication. Verifies Paystack HMAC-SHA512 signature from the `X-Paystack-Signature` header before processing.

### Reconciliation summary

```
GET /api/reconciliation/mpesa/
GET /api/reconciliation/paystack/
Authorization: Bearer <jwt>
```

Returns clearing balance and counts of unmatched, mismatched, and book-only settlements.

---

## Payment lifecycle

```
PENDING ──► PROCESSING ──► PAID
                      └──► FAILED
                      └──► CANCELLED
                      └──► EXPIRED
```

- `PENDING` → `PROCESSING`: STK Push is sent successfully; `provider_reference` (CheckoutRequestID) is stored.
- `PROCESSING` → `PAID`: M-Pesa callback received with `ResultCode: 0`, or `confirm_payment` Celery task queries M-Pesa and finds a successful result.
- `PROCESSING` → `CANCELLED`: User dismissed the STK prompt (`ResultCode: 1032`).
- `PROCESSING` → `EXPIRED`: `ResultCode: 1037`, or the payment is older than 60 minutes and still unresolved.
- `PROCESSING` → `FAILED`: Any other non-zero result code.

Terminal states (`PAID`, `FAILED`, `CANCELLED`, `EXPIRED`) cannot transition further.

---

## Celery tasks

| Task | Trigger | What it does |
|---|---|---|
| `confirm_payment` | Dispatched immediately after STK Push | Polls M-Pesa query API until the result is known; retries up to 6 times (15 s apart) |
| `reconcile_stuck_payments` | Celery Beat, every 5 minutes | Finds payments stuck in `processing` for >5 minutes; dispatches `reconcile_payment` for each |
| `reconcile_payment` | Dispatched by above | Queries provider for final status; expires payment after 60 minutes |
| `generate_receipt` | After `apply_status` marks PAID | Generates and stores a PDF receipt |

---

## Running tests

```bash
# All tests
pytest

# With verbose output
pytest -v

# Single test file
pytest payments/tests/test_callbacks.py -v
```

The test suite uses `pytest-django` with a session-scoped DB fixture. Set `CELERY_EAGER=1` in `.env` to run Celery tasks synchronously during tests.

---

## Adding a new payment provider

1. Create `payments/<provider>.py` and subclass `PaymentProvider` from `payments/base.py`:

```python
from .base import PaymentProvider, ChargeRequest, ChargeResponse, CallbackResult, CallbackOutcome

class AcmeProvider(PaymentProvider):
    name = "acme"

    def charge(self, req: ChargeRequest) -> ChargeResponse:
        # Call provider API, return ChargeResponse with provider_reference
        ...

    def parse_callback(self, *, headers, body, payload) -> CallbackResult:
        # Parse webhook body, return CallbackResult with outcome
        ...
```

2. Register it in `payments/registry.py`:

```python
from .acme import AcmeProvider

_PROVIDERS = {
    "mpesa": MpesaProvider,
    "paystack": PaystackProvider,
    "acme": AcmeProvider,  # add this
}
```

3. Add provider settings to `config/settings.py` and `.env`.

4. Register a callback URL in `payments/urls.py`:

```python
path("callbacks/acme/", AcmeCallbackView.as_view(), name="callback-acme"),
```

The `PaymentService.handle_callback()` and all state-machine logic are provider-agnostic — no other code needs to change.

---

## Settlement reconciliation

To reconcile a provider's settlements against the book:

1. Implement an adapter in `payments/adapters/` that parses the provider's statement CSV/JSON into `SettlementLine` objects (see `mpesa_statement.py` or `paystack_settlement.py` for examples).
2. Register it in `payments/adapters/registry.py`.
3. Ingest and reconcile:

```python
from payments.reconciliation import ReconciliationService
from payments.adapters.registry import get_adapter

adapter = get_adapter("mpesa")
lines = adapter.parse(open("statement.csv"))

svc = ReconciliationService()
svc.ingest("mpesa", lines)
report = svc.reconcile("mpesa")
print(report)
```

Or call the summary endpoint for a quick dashboard view: `GET /api/reconciliation/mpesa/`.
