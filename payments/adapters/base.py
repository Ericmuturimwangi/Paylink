from __future__ import annotations
import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


def parse_amount_minor(value: str, currency: str) -> int:
    if not value or not value.strip():
        return 0
    return round(float(value.strip().replace(",", "")) * 100)


def parse_dt(value: str) -> datetime.datetime:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt).replace(
                tzinfo=datetime.timezone.utc
            )
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {value!r}")


@dataclass
class SettlementLine:
    txn_ref: str
    gross_minor: int
    fee_minor: int
    net_minor: int
    currency: str
    settled_at: datetime.datetime
    raw: dict = field(default_factory=dict)


class SettlementAdapter(ABC):
    @abstractmethod
    def parse(self, fh) -> list[SettlementLine]:
        ...
