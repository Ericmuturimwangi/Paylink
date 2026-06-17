from __future__ import annotations

from django.db import transaction

from .models import Payment, WebhookEvent, AuditLog, AuditEvent
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
        AuditLog.record(
            payment = payment, event = AuditEvent.CREATED, source="api",
            summary = f"payment created for {money.major} {money.currency}",
            to_status = PaymentStatus.PENDING.value,
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
        except Exception as exc:
            payment.transition_to(PaymentStatus.FAILED)
            payment.save(update_fields=["status", "updated_at"])
            AuditLog.record(
                payment=payment, event=AuditEvent.CHARGE_FAILED, source="api",
                summary="provider rejected the charge",
                from_status=PaymentStatus.PENDING.value,
                to_status = PaymentStatus.FAILED.value,
                metadata = {"error": str(exc)},
            )
            raise

        payment.provider_reference = resp.provider_reference
        payment.merchant_request_id = resp.extra.get("merchant_request_id", "")
        payment.transition_to(PaymentStatus.PROCESSING)
        payment.save(update_fields= [
            "provider_reference", "merchant_request_id", "status", "updated_at",
        ])

        AuditLog.record(
            payment = payment, event = AuditEvent.STK_INITIATED, source="api",
            summary  = "charge accepted: awaiting sync confirmation",
            from_status = PaymentStatus.PENDING.value,
            to_status = PaymentStatus.PROCESSING.value,
            metadata = {"provider_reference": resp.provider_reference,
                        "merchant_request_id": payment.merchant_request_id
                        },
        )

        if not provider.callback_is_authoritative():
            from .tasks import confirm_payment
            transaction.on_commit(
                lambda: confirm_payment.apply_async((str(payment.id),), countdown=40)
            )
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
            self._apply(payment, result.outcome, result.provider_receipt)
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
    def apply_status(self, *, payment_id, outcome: CallbackOutcome, provider_receipt: str = "") -> bool:

        payment = Payment.objects.select_for_update().filter(pk=payment_id).first()
        if payment is None:
            return False

        return self._apply(payment, outcome, provider_receipt)

    @staticmethod
    def _apply(payment: Payment, outcome: CallbackOutcome, provider_receipt: str) -> bool:
        target = _OUTCOME_TO_STATUS.get(outcome)
        if target is None:
            return False
        try:
            changed = payment.transition_to(target)
        except Exception:
            changed = False
        if changed and provider_receipt:
            payment.provider_receipt = provider_receipt
        payment.save()

        return changed



        

