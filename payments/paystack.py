from __future__ import annotations

import hashlib
import hmac

from django.conf import settings

from .base import(
    PaymentProvider, ChargeRequest, ChargeResponse, CallbackResult, CallbackOutcome,
)

class PaystackProvider(PaymentProvider):
    name = "paystack"

    def charge(self, req: ChargeRequest) -> ChargeResponse:

        raise NotImplementedError("Paystack charge deffered to the next slice")

    def parse_callback(self, *, headers, body, payload) -> CallbackResult:

        secret = settings.PAYSTACK["SECRET_KEY"].encode()
        expected = hmac.new(secret, body, hashlib.sha512).hexdigest()
        provided = headers.get("x-paystack-signature", "")
        if not hmac.compare_digest(expected, provided):
            raise PermissionError("Invalid Paystack signature")


        event = payload.get("event")
        data = payload.get("data", {})
        reference = data.get("reference", "")
        outcome ={
            "charge.success": CallbackOutcome.PAID,
            "charge.failed": CallbackOutcome.FAILED,
        }.get(event, CallbackOutcome.UNKNOWN)

        return CallbackResult(
            dedupe_key = str(payload.get("id") or reference),
            outcome = outcome,
            provider_reference = reference,
            raw = payload,
        )
        