from django.urls import path

from .views import (
    CreatePaymentView,
    PaymentStatusVIew,
    MpesaCallbackView,
    PaystackCallbackView,
)

urlpatterns = [
    path("payments/", CreatePaymentView.as_view(), name="payment-create"),
    path("payments/<uuid:pk>/status/", PaymentStatusVIew.as_view(), name="payment-status"),
    path("callbacks/mpesa/", MpesaCallbackView.as_view(), name="callback-mpesa"),
    path("callbacks/paystack/", PaystackCallbackView.as_view(), name="callback-paystack"),
]
