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

class AuditEvent(models.TextChoices):
    CREATED = "payment.created"
    STK_INITIATED = "stk.initiated"
    CHARGE_FAILED = "charge.failed"
    CALLBACK_RECEIVED = "callback.received"
    QUERY_PERFORMED = "query.performed"
    STATUS_CHANGED = "status.changed"

class AuditLog(models.Model):

    id  = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, related_name="audit_logs"
    )
    event = models.CharField(max_length=32, choices=AuditEvent.choices)

    source = models.CharField(max_length=32)
    summary = models.CharField(max_length=255, blank=True)
    from_status = models.CharField(max_length=16, blank=True)
    to_status = models.CharField(max_length=16, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        ordering = ["created_at"]
        indexes = [models.Index(fields=["payment", "created_at"])]

    @classmethod
    def record(cls, *, payment, event, source, summary="", from_status="", 
                to_status="", metadata=None):
        return cls.objects.create(
            payment=payment,
            event=event,
            source=source,
            summary=summary,
            from_status=from_status,
            to_status=to_status,
            metadata=metadata or {},
        )

    def save(self, *args, **kwargs):
        if self.pk and AuditLog.objects.filter(pk=self.pk).exists():
            raise ValueError("AuditLog is append-only: rows cannot be modified")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog is append-only: rows cannot be deleted")

