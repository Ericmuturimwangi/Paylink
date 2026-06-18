import pytest


@pytest.fixture(autouse=True)
def _hermetic_settings(settings, tmp_path):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_TASK_EAGER_PROPAGATES = True
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.MPESA = {
        "BASE_URL": "https://sandbox.safaricom.co.ke", "SHORTCODE": "174379",
        "PASSKEY": "testpasskey", "CONSUMER_KEY": "ck", "CONSUMER_SECRET": "cs",
        "CALLBACK_URL": "https://example.test/api/webhooks/mpesa/",
    }
    settings.PAYSTACK = {"SECRET_KEY": "sk_test_x"}


@pytest.fixture
def charge_ok():

    from unittest.mock import patch
    from payments.base import ChargeResponse

    def _charge(req):
        return ChargeResponse(
            provider_reference=f"ws_CO_{req.reference}",
            extra={"merchant_request_id": "mr_1"}, raw={},
        )

    with patch("payments.mpesa.MpesaProvider.charge", side_effect=_charge) as m:
        yield m


@pytest.fixture
def make_payment(db, charge_ok):
    from payments.services import PaymentService
    svc = PaymentService()
    seq = {"n": 0}

    def _make(amount="150.00", currency="KES", phone="254712345678",
              provider="mpesa", ref=None):
        seq["n"] += 1
        ref = ref or f"ORD{seq['n']}"
        return svc.create_and_charge(
            provider_name=provider, amount_major=amount, currency=currency,
            customer_phone=phone, description="test", reference=ref,
            idempotency_key=f"idem-{ref}",
        )

    return _make


@pytest.fixture
def make_paid(make_payment):
    from payments.services import PaymentService
    from payments.base import CallbackOutcome
    svc = PaymentService()

    def _make(amount="150.00", receipt="MPESA_RC", ref=None, **kw):
        p = make_payment(amount=amount, ref=ref, **kw)
        svc.apply_status(payment_id=str(p.id), outcome=CallbackOutcome.PAID,
                         provider_receipt=receipt, source="confirm_task",
                         query_metadata={})
        p.refresh_from_db()
        return p

    return _make