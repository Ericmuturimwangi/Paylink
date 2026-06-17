from __future__ import annotations

from celery import shared_task
from .states import PaymentStatus
from .models import Payment
from .base import CallbackOutcome
from .registry import get_provider
from .services import PaymentService

_OPEN = {PaymentStatus.PENDING, PaymentStatus.PROCESSING}

@shared_task(bind=True, max_retries=6, default_retry_delay=15)

def confirm_payment(self, payment_id: str):
    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None:
        return "gone"

    if PaymentStatus(payment.status) not in _OPEN:
        return f"already {payment.status}"

    if not payment.provider_reference:
        return "no provider_reference yet"

    provider = get_provider(payment.provider)
    result= provider.query_status(payment.provider_reference)

    if result.outcome == CallbackOutcome.UNKNOWN:

        raise self.retry()

    PaymentService().apply_status(
        payment_id=payment_id,
        outcome=result.outcome,
        provider_receipt=result.provider_receipt,
    )

    return result.outcome.value  


RECONCILE_MIN_AGE = timedelta(minutes=5)
RECONCILE_MAX_AGE = timedelta(minutes=60)
RECONCILE_BATCH = 200

@shared_task
def reconcile_stuck_payments():
    cutoff = timezone.now() - RECONCILE_MIN_AGE
    stuck_ids = list(
        Payment.objects.filter(
            status=PaymentStatus.PROCESSING.value,
            created_at__lt=cutoff,
        )
        .order_by("created_at")
        .values_list("id", flat=True)[:RECONCILE_BATCH]
    )
    for pid in stuck_ids:
        reconcile_stuck_payments.delay(str(pid))
    return f"dispatched {len(stuck_ids)}"


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def reconcile_payment(self, payment_id: str):

    payment = Payment.objects.filter(pk=payment_id).first()
    if payment is None:
        return "gone"
    if PaymentStatus(payment.status) not in _OPEN:
        return f"already {payment.status}"
    if not payment.provider_reference:
        return "no provider_reference"

    
    provider = get_provider(payment.provider)
    try:
        result = provider.query_status(payment.provider_reference)
    except NotImplementedError:
        result = None

    if result is not None and result.outcome != CallbackOutcome.UNKNOWN:
        PaymentService().apply_status(
            payment_id=payment_id,
            outcome=result.outcome,
            provider_receipt=result.provider_receipt,
            source="reconcile_task",
            query_metadata=result.raw,
        )

        return result.outcome.value   

    if timezone.now() - payment.created_at >= RECONCILE_MAX_AGE:
        PaymentService().apply_status(
            payment_id=payment_id, 
            outcome=CallbackOutcome.EXPIRED,
            source = "reconcile_task",
            query_metadata = {"reason": "max_age_exceeded",
                            "last_query": (result.raw if result is not None else None)},
            )
        return "expired"

    raise self.retry()



