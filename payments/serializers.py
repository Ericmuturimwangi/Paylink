from __future__ import annotations

from rest_framework import serializers

from .registry import available

class CreatePaymentSerializer(serializers.Serializer):
    provider = serializers.ChoiceField(choices=available())
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    currency = serializers.CharField(max_length=3, default="KES")
    customer_phone = serializers.CharField(max_length=20)
    description = serializers.CharField(
        max_length = 255, required=False, allow_blank = True, default="",
    )

    reference = serializers.CharField(max_length=32)


class PaymentStatusSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    provider = serializers.CharField()
    currency = serializers.CharField()
    provider_receipt = serializers.CharField()
    amount = serializers.SerializerMethodField()

    def get_amount(self, obj) -> str:
        from .money import Money
        return str(Money(obj.amount_minor, obj.currency).major)


class AuditLogSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    event = serializers.CharField()
    source = serializers.CharField()
    summary = serializers.CharField()
    from_status = serializers.CharField()
    to_status = serializers.CharField()
    metadata = serializers.JSONField()
    created_at = serializers.DateTimeField()
        