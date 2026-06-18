from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from .money import Money

class CallbackOutcome(str, Enum):
    PAID = "paid"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

@dataclass
class ChargeRequest:
    payment_id: str
    money: Money
    customer_phone: str
    description: str
    reference: str

@dataclass
class ChargeResponse:
    provider_reference: str
    extra: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)

@dataclass
class CallbackResult:
    dedupe_key: str
    outcome: CallbackOutcome
    provider_reference: str
    provider_receipt: str = ""
    raw: dict = field(default_factory=dict)

class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def charge(self, req: ChargeRequest) -> ChargeResponse:
        """ initiate a collection"""

    @abstractmethod
    def parse_callback(self, *, headers: dict, body: bytes, payload: dict) -> CallbackResult:
        """normalise a provider webhook into a callback """


    def callback_is_authoritative(self) -> bool:
        return True

    def supports_refund(self) -> bool:
        return False

    def refund(Self, payment) -> dict:
        raise NotImplementedError(f"{self.name} does not support refunds through this interface")

