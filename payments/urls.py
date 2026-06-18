from django.urls import path

from .views import (
    CreatePaymentView,
    PaymentStatusVIew,
    PaymentAuditView,
    MpesaCallbackView,
    PaystackCallbackView,
    ReceiptDownloadView,
    ReconciliationSummaryView,
)

urlpatterns = [
    path("payments/", CreatePaymentView.as_view(), name="payment-create"),
    path("payments/<uuid:pk>/status/", PaymentStatusVIew.as_view(), name="payment-status"),
    path("payments/<uuid:pk>/audit/", PaymentAuditView.as_view(), name="payment-audit"),
    path("payments/<uuid:pk>/receipt/", ReceiptDownloadView.as_view(), name="payment-receipt"),
    path("callbacks/mpesa/", MpesaCallbackView.as_view(), name="callback-mpesa"),
    path("callbacks/paystack/", PaystackCallbackView.as_view(), name="callback-paystack"),
    path("webhooks/mpesa/", MpesaCallbackView.as_view(), name="webhook-mpesa"),
    path("webhooks/paystack/", PaystackCallbackView.as_view(), name="webhook-paystack"),
    path("reconciliation/<str:provider>/", ReconciliationSummaryView.as_view(), name="reconciliation-summary"),
]
