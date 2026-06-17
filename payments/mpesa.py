from __future__ import annotations
import base64
import datetime as dt  
import requests
from django.conf import settings

from .base import(
    PaymentProvider, ChargeRequest, ChargeResponse, CallbackResult, CallbackOutcome,
)

class MpesaProvider(PaymentProvider):
    name = "mpesa"

    def __init__(self) -> None:
        cfg = settings.MPESA
        self.base_url = cfg["BASE_URL"]
        self.shortcode = cfg["SHORTCODE"]
        self.passkey = cfg["PASSKEY"]
        self.consumer_key = cfg["CONSUMER_KEY"]
        self.consumer_secret = cfg["CONSUMER_SECRET"]
        self.callback_url = cfg["CALLBACK_URL"]

    def _token(self) -> str:

        r = requests.get(
            f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials",
            auth = (self.consumer_key, self.consumer_secret),
            timeout = 30,
        )
        r.raise_for_status()
        return r.json()["access_token"]

    @staticmethod
    def _normalise_phone(phone: str) -> str:
        p = phone.strip().replace("+", "").replace(" ", "")
        if p.startswith("0"):
            p = "254" + p[1:]
        if not (p.startswith("254") and len(p) == 12 and p.isdigit()):
            raise ValueError(f"Invalid M-Pesa phone: {phone!r}")
        return p

    def charge(self, req: ChargeRequest) -> ChargeResponse:
        ts = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            f"{self.shortcode}{self.passkey}{ts}".encode()
        ).decode()
        phone = self._normalise_phone(req.customer_phone)

        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": ts,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": req.money.whole_units(),
            "PartyA": phone,
            "PartyB": self.shortcode,
            "PhoneNumber": phone,
            "CallBackURL": self.callback_url,
            "AccountReference": req.reference[:12],
            "TransactionDesc": (req.description or "Payment")[:13],
        }

        r = requests.post(
            f"{self.base_url}/mpesa/stkpush/v1/processrequest",
            json=payload,
            headers ={"Authorization": f"Bearer {self._token()}"},
            timeout = 30,
        )
        r.raise_for_status()
        data = r.json()
        if str(data.get("ResponseCode")) != "0":
            raise RuntimeError(f"STK Push rejected: {data}")
        return ChargeResponse(
            provider_reference = data["CheckoutRequestID"],
            extra = {"merchant_request_id": data["MerchantRequestID"]},
            raw=data,
        )

    def parse_callback(self, *, headers, body, payload) -> CallbackResult:

        cb = payload["Body"]["stkCallback"]
        checkout_id = cb["CheckoutRequestID"]
        result_code = int(cb["ResultCode"])

        if result_code == 0:
            items = {i["Name"]: i.get("Value") for i in cb["CallbackMetadata"]["Item"]}
            return CallbackResult(
                dedupe_key=checkout_id,
                outcome=CallbackOutcome.PAID,
                provider_reference=checkout_id,
                provider_receipt=str(items.get("MpesaReceiptNumber", "")),
                raw=payload,
            )

        outcome ={
            1032: CallbackOutcome.CANCELLED,
            1037: CallbackOutcome.EXPIRED,
            1: CallbackOutcome.FAILED,
        }.get(result_code, CallbackOutcome.FAILED)

        return CallbackResult(
            dedupe_key=checkout_id,
            outcome=outcome,
            provider_reference=checkout_id,
            raw=payload,
        )

    def callback_is_authoritative(self) -> bool:
        return False
    
    def query_status(self, provider_reference: str) -> CallbackResult:

        ts = dt.datetime.now().strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            f"{self.shortcode}{self.passkey}{ts}".encode()
        ).decode()

        r = requests.post(
            f"{self.base_url}/mpesa/stkpushquery/v1/query",
            json = {
                "BusinessShortCode": self.shortcode,
                "Password": password,
                "Timestamp": ts,
                "CheckoutRequestID": provider_reference,
            },
            headers = {"Authorization": f"Bearer {self._token()}"},
            timeout = 30,
        )
        data = r.json()

        if "errorCode" in data:
            return CallbackResult(
                dedupe_key=f"query:{provider_reference}",
                outcome=CallbackOutcome.UNKNOWN,
                provider_reference=provider_reference,
                raw=data,
            )

        result_code = int(data["ResultCode"])
        if result_code == 0:
            outcome = CallbackOutcome.PAID
        else:
            outcome = {
                1032: CallbackOutcome.CANCELLED,
                1037: CallbackOutcome.EXPIRED,
                1: CallbackOutcome.FAILED,
            }.get(result_code, CallbackOutcome.FAILED)
        return CallbackResult(
            dedupe_key=f"query:{provider_reference}",
            outcome=outcome,
            provider_reference=provider_reference,
            raw=data,
        )

    def supports_refund(self) -> bool:
        return False
        

