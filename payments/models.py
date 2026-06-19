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
    reference = models.CharField(max_length=64, blank=True, db_index=True)

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
    RECEIPT_GENERATED = "receipt.generated"

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

class Receipt(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    payment = models.OneToOneField(
        Payment, on_delete=models.PROTECT, related_name="receipt"
    )

    receipt_number = models.CharField(max_length=40, unique=True)
    pdf = models.FileField(upload_to="receipts/")
    generated_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return self.receipt_number


class SettlementStatus(models.TextChoices):
    UNMATCHED = "unmatched"
    MATCHED = "matched"
    AMOUNT_MISMATCH = "amount_mismatch"
    NO_BOOK_ENTRY = "no_book_entry"


class SettlementRecord(models.Model):

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.CharField(max_length=32)
    txn_ref = models.CharField(max_length=64)
    gross_minor = models.BigIntegerField()
    fee_minor = models.BigIntegerField(default=0)
    net_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    settled_at = models.DateTimeField()
    status = models.CharField(
        max_length=20, default=SettlementStatus.UNMATCHED, choices=SettlementStatus.choices
    )
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.PROTECT, related_name="settlements",
    )

    raw = models.JSONField(default = dict, blank=True)
    import_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints =[
            models.UniqueConstraint(fields=["provider", "txn_ref"], name="uniq_settlement_ref"),
        ]
        indexes= [models.Index(fields=["provider", "status"])]


class LedgerSide(models.TextChoices):
    DEBIT = "DR"
    CREDIT = "CR"


class Account(models.TextChoices):
    MPESA_CLEARING = "mpesa_clearing"
    PAYSTACK_CLEARING = "paystack_clearing"
    BANK = "bank"
    REVENUE = "revenue"
    FEES = "fees"


class LedgerEntry(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group = models.UUIDField(db_index=True)
    purpose = models.CharField(max_length=16)
    account = models.CharField(max_length=24, choices=Account.choices)
    side = models.CharField(max_length=2, choices=LedgerSide.choices)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    payment = models.ForeignKey(
        Payment, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    settlement = models.ForeignKey(
        SettlementRecord, null=True, blank=True, on_delete=models.PROTECT, related_name="ledger_entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["account", "side"]),
            models.Index(fields=["payment", "purpose"]),
        ]

    def save(self, *args, **kwargs):
        if self.pk and LedgerEntry.objects.filter(pk=self.pk).exists():
            raise ValueError("LedgerEntry is append-only: rows cannot be modified")
        super().save(*args, **kwargs)
        

    def delete(self, *args, **kwargs):
        raise ValueError("LedgerEntry is append-only: rows cannot be deleted")

        