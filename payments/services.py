from __future__ import annotations

from django.db import transaction

from .models import Payment, WebhookEvent
from .money import Money
from .states import PaymentStatus
from .base import ChargeRequest, CallbackOutcome, CallbackResult
from .registry import get_provider

_OUTCOME_TO_STATUS = {
    CallbackOutcome.PAID: PaymentStatus.PAID,
    CallbackOutcome.FAILED:PaymentStatus.FAILED,
    CallbackOutcome.CANCELLED:PaymentStatus.CANCELLED,
    CallbackOutcome.EXPIRED:PaymentStatus.EXPIRED,
}

class PaymentService:

    @transaction.atomic
    def create_and_charge(
        self, *, provider_name, amount_major, currency, customer_phone, description, reference, idempotency_key,
    ) -> Payment:
        existing = Payment.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing


        money = Money.from_major(amount_major, currency)
        payment = Payment.objects.create(
            provider = provider_name,
            amount_minor = money.minor,
            currency = money.currency,
            customer_phone = customer_phone,
            description = description,
            idempotency_key = idempotency_key,
            status = PaymentStatus.PENDING.value,
        ) 

        provider = get_provider(provider_name)
        try:
            resp = provider.charge(ChargeRequest(
                payment_id = str(payment.id),
                money = money,
                customer_phone = customer_phone,
                description = description,
                reference = reference,
            ))
        except Exception:
            payment.transition_to(PaymentStatus.FAILED)
            payment.save(update_fields=["status", "updated_at"])
            raise

        payment.provider_reference = resp.provider_reference
        payment.merchant_request_id = resp.extra.get("merchant_request_id", "")
        payment.transition_to(PaymentStatus.PROCESSING)
        payment.save(update_fields= [
            "provider_reference", "merchant_request_id", "status", "updated_at",
        ])
        return payment


    @transaction.atomic
    def handle_callback(self, *, provider_name: str, result: CallbackResult) -> bool:

        event, created = WebhookEvent.objects.select_for_update().get_or_create(
            provider=provider_name,
            dedupe_key=result.dedupe_key,
            defaults={"payload": result.raw},
        )

        if not created and event.processed:
            return False

        payment =(
            Payment.objects.select_for_update()
            .filter(provider=provider_name, provider_reference=result.provider_reference)
            .first()
        )

        if payment is None:
            event.processed = True
            event.save(update_fields=["processed"])
            return False

        target = _OUTCOME_TO_STATUS.get(result.outcome)

        if target is not None:
            try:
                changed = payment.transition_to(target)

            except Exception:
                
                changed = False
            if changed and result.provider_receipt:
                payment.provider_receipt = result.provider_receipt

            payment.save()


        event.processed = True
        event.save(update_fields=['processed'])

        return True
        

