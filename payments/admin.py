from __future__ import annotations

from django.contrib import admin

from .models import Payment, WebhookEvent, AuditLog

class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

class AuditLogInLine(admin.TabularInline):
    model = AuditLog
    extra = 0
    can_delete = False
    ordering = ("created_at",)
    fields = ("created_at", "event", "source", "summary", "from_status", "to_status")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ("id", "provider", "status", "amount_minor", "currency", "provider_receipt", "created_at"
    )
    list_filter = ("provider", "status", "currency")
    search_fields = ["id", "provider_reference", "provider_receipt", "idempotency_key", "customer_phone"]
    inlines = [AuditLogInLine]


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "payment", "event", "source", "summary")
    list_filter = ("event", "source")
    search_fields = ["payment__id", "summary"]


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ("received_at", "provider", "dedupe_key", "processed")
    list_filter = ("provider", "processed")
    search_fields = ["dedupe_key"]



