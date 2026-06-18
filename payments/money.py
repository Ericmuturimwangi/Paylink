from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

_EXPONENT = {"KES": 2, "USD": 2, "NGN": 2, "EUR": 2, "GBP": 2, "JPY": 0}


@dataclass(frozen=True)
class Money:
    minor:int
    currency: str


    def __post_init__(self) -> None:
        if self.currency not in _EXPONENT:
            raise ValueError(f"Unsupported currency: {self.currency!r}")
        if not isinstance(self.minor, int):
            raise TypeError("Money.minor must be int (minor units)")
        if self.minor < 0:
            raise ValueError("Money.minor must be non-negative")


    @classmethod
    def from_major(cls, amount, currency: str) -> "Money":

        if currency not in _EXPONENT:
            raise ValueError(F"Unsupported currency: {currency!r}")
        scaled = Decimal(str(amount)).scaleb(_EXPONENT[currency])
        if scaled != scaled.to_integral_value():
            raise ValueError(f"{amount} {currency} has sub-minor-unit precision")
        return cls(int(scaled), currency)


    @property
    def major(self) -> Decimal:
        return Decimal(self.minor) /(10 ** _EXPONENT[self.currency])

    def whole_units(self) -> int:

        scale = 10 ** _EXPONENT[self.currency]
        if self.minor % scale != 0:
            raise ValueError(
                f"{self.major} {self.currency} is not a whole unit: "
                "M-Pesa STK required whole-shilling amounts"
            )

        return self.minor // scale

        