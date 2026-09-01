from __future__ import annotations

import logging

from django.db import transaction

from .models import Payment, WebhookEvent, AuditLog, AuditEvent
from .money import Money
from .states import PaymentStatus
from .base import ChargeRequest, CallbackOutcome, CallbackResult
from .registry import get_provider
from .signals import payment_paid

logger = logging.getLogger(__name__)


_OUTCOME_TO_STATUS = {
    CallbackOutcome.PAID: PaymentStatus.PAID,
    CallbackOutcome.FAILED:PaymentStatus.FAILED,
    CallbackOutcome.CANCELLED:PaymentStatus.CANCELLED,
    CallbackOutcome.EXPIRED:PaymentStatus.EXPIRED,
}

class PaymentService:

    def create_and_charge(
        self, *, provider_name, amount_major,
        currency, customer_phone, 
        description, reference, idempotency_key,
    ) -> Payment:

        payment, created = self._ensure_pending(
            provider_name = provider_name, amount_major=amount_major, currency=currency,
            customer_phone = customer_phone, description=description,
            reference=reference, idempotency_key=idempotency_key,
        )
        if not created and payment.status != PaymentStatus.PENDING.value:
            return payment

        provider = get_provider(provider_name)
        try:
            resp = provider.charge(ChargeRequest(
                payment_id=str(payment.id),
                money=Money(payment.amount_minor, payment.currency),
                customer_phone=customer_phone,
                description=description,
                reference=reference,
            ))
        except Exception as exc:
            self._mark_charge_failed(payment, exc)
            raise

        self._mark_processing(
            payment, resp, authoritative = provider.callback_is_authoritative()
        )
        return payment
    
    @transaction.atomic
    def _ensure_pending(self, *, provider_name, amount_major, currency, customer_phone, description, reference, idempotency_key):

        money = Money.from_major(amount_major, currency)
        payment, created = Payment.objects.get_or_create(
            idempotency_key=idempotency_key,
            defaults= dict(
                provider=provider_name, amount_minor=money.minor, currency=money.currency,
                customer_phone = customer_phone, description=description,
                reference=reference, status=PaymentStatus.PENDING.value,
            ),
        )
        if created:
            AuditLog.record(
                payment=payment, event=AuditEvent.CREATED, source="api",
                summary=f"payment created for {money.major} {money.currency}",
                to_status= PaymentStatus.PENDING.value,
            )
        return payment, created

    @transaction.atomic
    def _mark_charge_failed(self, payment, exc):
        payment.transition_to(PaymentStatus.FAILED)
        payment.save(update_fields=["status", "updated_at"])
        AuditLog.record(
            payment=payment, event=AuditEvent.CHARGE_FAILED, source="api",
            summary="provider rejected the charge",
            from_status=PaymentStatus.PENDING.value, to_status=PaymentStatus.FAILED.value,
            metadata={"error": str(exc)},
        )

    @transaction.atomic
    def _mark_processing(self, payment, resp, *, authoritative):
        payment.provider_reference = resp.provider_reference
        payment.merchant_request_id = resp.extra.get("merchant_request_id", "")
        payment.transition_to(PaymentStatus.PROCESSING)
        payment.save(update_fields=[
            "provider_reference", "merchant_request_id", "status", "updated_at",
        ])
        AuditLog.record(
            payment=payment, event=AuditEvent.STK_INITIATED, source="api",
            summary="charge accepted: awaiting async confirmation",
            from_status = PaymentStatus.PENDING.value,
            to_status= PaymentStatus.PROCESSING.value,
            metadata={"provider_reference": resp.provider_reference,
            "merchant_request_id": payment.merchant_request_id},
        )

        if not authoritative:
            from .tasks import confirm_payment
            transaction.on_commit(
                lambda: confirm_payment.apply_async((str(payment.id),), countdown=40)

            )

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


        provider = get_provider(provider_name)
        AuditLog.record(
            payment= payment, event=AuditEvent.CALLBACK_RECEIVED,
            source = f"{provider_name}_callback",
            summary = f"callback outcome={result.outcome.value}, "
                    f"authoritative={provider.callback_is_authoritative()}",
            metadata = {"dedupe_key": result.dedupe_key,
                        "receipt": result.provider_receipt},
        )

        if provider.callback_is_authoritative():
            self._apply(payment, result.outcome, result.provider_receipt, source=f"{provider_name}_callback")
        else:

            if result.provider_receipt:
                payment.provider_receipt = result.provider_receipt
                payment.save(update_fields=["provider_receipt", "updated_at"])
            from .tasks import confirm_payment
            transaction.on_commit(
                lambda: confirm_payment.delay(str(payment.id))
            )

        event.processed = True
        event.save(update_fields=["processed"])
        return True

    @transaction.atomic
    def apply_status(self, *, payment_id, outcome: CallbackOutcome, provider_receipt: str = "",
                     source: str = "", query_metadata: dict | None = None) -> bool:
        payment = Payment.objects.select_for_update().filter(pk=payment_id).first()
        if payment is None:
            return False
        if query_metadata is not None:
            AuditLog.record(
                payment=payment, event=AuditEvent.QUERY_PERFORMED, source=source,
                summary=f"provider query -> {outcome.value}",
                metadata=query_metadata,
            )
        return self._apply(payment, outcome, provider_receipt, source=source)

    @staticmethod
    def _apply(payment: Payment, outcome: CallbackOutcome, provider_receipt: str,
               source: str = "") -> bool:
        target = _OUTCOME_TO_STATUS.get(outcome)
        if target is None:
            return False
        from_status = payment.status
        try:
            changed = payment.transition_to(target)
        except Exception:
            changed = False
        if changed and provider_receipt:
            payment.provider_receipt = provider_receipt
        payment.save()
        if changed:
            AuditLog.record(
                payment=payment, event=AuditEvent.STATUS_CHANGED, source=source,
                summary=f"{from_status} -> {target.value}",
                from_status=from_status, to_status=target.value,
            )
            if target == PaymentStatus.PAID:
                
                pid = str(payment.id)

                def _on_paid(p=payment):
                    from .tasks import generate_receipt
                    generate_receipt.delay(pid)

                    for receiver, exc in payment_paid.send_robust(sender=Payment, payment=p):
                        if exc is not None:
                            logger.error(
                                "payment_paid receiver %r failed for payment %s: %s",
                                receiver, pid, exc,
                            )
                transaction.on_commit(_on_paid)
        return changed

 



        

