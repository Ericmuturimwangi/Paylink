from __future__ import annotations
import uuid

from django.db import models

from .states import PaymentStatus, IllegalTransition, can_transition

class Payment(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)

    provider = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16, 
        default=PaymentStatus.PENDING.value,
        choices=[(s.value, s.value) for s in PaymentStatus],
    )

    customer_phone = models.CharField(max_length=20, blank=True)
    customer_email = models.EmailField(blank=True)
    description = models.CharField(max_length=255, blank=True)

    provider_reference = models.CharField(max_length=128, blank=True)
    merchant_request_id = models.CharField(max_length=128, blank=True)
    provider_receipt = models.CharField(max_length=64, blank=True)

    idempotency_key = models.CharField(max_length=64, unique=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "provider_reference"]),
            models.Index(fields=["status", "created_at"]),
        ]

    def transition_to(self, new_status: PaymentStatus) -> bool:

        current = PaymentStatus(self.status)
        if current == new_status:
            return False
        if not can_transition(current, new_status):
            raise IllegalTransition(f"{self.status} -> {new_status.value}")

        self.status = new_status.value  
        return True


class WebhookEvent(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32)
    dedupe_key = models.CharField(max_length=128)
    payload = models.JSONField()
    received_at = models.DateTimeField(auto_now_add=True)
    processed = models.BooleanField(default=False)


    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "dedupe_key"], name="uniq_provider_dedupe"
            ),
        ]

        indexes = [models.Index(fields=["provider", "dedupe_key"])]

