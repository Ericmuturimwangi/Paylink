from __future__ import annotations
import csv
from .base import SettlementAdapter, SettlementLine, parse_amount_minor, parse_dt


class PaystackSettlementAdapter(SettlementAdapter):
    def parse(self, fh) -> list[SettlementLine]:
        reader = csv.DictReader(fh)
        lines = []
        for row in reader:
            ref = row.get("reference", "").strip()
            if not ref:
                continue
            currency = row.get("currency", "KES").strip()
            gross = parse_amount_minor(row.get("amount", "0"), currency)
            fee = parse_amount_minor(row.get("fees", "0"), currency)
            lines.append(SettlementLine(
                txn_ref=ref,
                gross_minor=gross,
                fee_minor=fee,
                net_minor=gross - fee,
                currency=currency,
                settled_at=parse_dt(row.get("settled_at", "")),
                raw=dict(row),
            ))
        return lines
