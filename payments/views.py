from __future__ import annotations

from rest_framework import status as http
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Payment
from .registry import get_provider
from .services import PaymentService
from .serializers import CreatePaymentSerializer, PaymentStatusSerializer

service = PaymentService()

class CreatePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        idem = request.headers.get("Idempotent-Key")
        if not idem:
            return Response(
                {"detail": "Idempotency-Key header required"},
                status=http.HTTP_400_BAD_REQUEST,
            )

        s = CreatePaymentSerializer(data = request.data)
        s.is_valid(raise_exception=True)
        payment = service.create_and_charge(
            provider_name = s.validated_data["provider"],
            amount_major = s.validated_data["amount"],
            currency = s.validated_data["currency"],
            customer_phone = s.validated_data["customer_phone"],
            description = s.validated_data["description"],
            reference = s.validated_data["reference"],
            idempotency_key = idem,
        )

        return Response(
            PaymentStatusSerializer(payment).data, status=http.HTTP_201_CREATED
        )

class PaymentStatusVIew(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        payment = Payment.objects.filter(pk=pk).first()
        if payment is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        
        return Response(PaymentStatusSerializer(payment).data)


class PaymentAuditView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        payment = Payment.objects.filter(pk=pk).first()
        if payment is None:
            return Response(status=http.HTTP_404_NOT_FOUND)
        logs = payment.audit_logs.all()
        return Response(AudtiLogSerializer(logs, many=True).data) 

class MpesaCallbackView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        provider = get_provider("mpesa")
        result = provider.parse_callback(
            headers = request.headers, body=request.body, payload = request.data,
        )
        service.handle_callback(provider_name="mpesa", result=result)
        return Response({"ResultCode": 0, "ResultDesc": "Accepted"})


class PaystackCallbackView(APIView):

    permission_classes = [AllowAny]

    def post(self, request):
        provider = get_provider("paystack")

        try:
            result = provider.parse_callback(
                headers= request.headers, body=request.body, payload=request.data,
            )
        except PermissionError:
            return Response(status=http.HTTP_401_UNAUTHORIZED)

        service.handle_callback(provider_name="paystack", result=result)

        return Response(status=http.HTTP_200_OK)

        