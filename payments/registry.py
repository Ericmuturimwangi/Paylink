from __future__ import annotations

from typing import Callable

from .base import PaymentProvider
from .mpesa import MpesaProvider
from .paystack import PaystackProvider

_FACTORIES: dict[str, Callable[[], PaymentProvider]] = {
    "mpesa": MpesaProvider,
    "paystack": PaystackProvider,
}


def get_provider(name: str) -> PaymentProvider:
    try:
        return _FACTORIES[name]()
    except KeyError:
        raise KeyError(f"Unknown provider: {name!r}")


def available() -> list[str]:

    return sorted(_FACTORIES)

