from __future__ import annotations
import csv
from .base import SettlementAdapter, SettlementLine, parse_amount_minor, parse_dt


class MpesaStatementAdapter(SettlementAdapter):
    def parse(self, fh) -> list[SettlementLine]:
        reader = csv.reader(fh)
        header = None
        lines = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            if header is None:
                if row and row[0].strip() == "Receipt No.":
                    header = [c.strip() for c in row]
                continue
            rec = dict(zip(header, [c.strip() for c in row]))
            if rec.get("Transaction Status") != "Completed":
                continue
            paid_in = rec.get("Paid In", "").strip()
            if not paid_in:
                continue
            gross = parse_amount_minor(paid_in, "KES")
            lines.append(SettlementLine(
                txn_ref=rec["Receipt No."],
                gross_minor=gross,
                fee_minor=0,
                net_minor=gross,
                currency="KES",
                settled_at=parse_dt(rec["Completion Time"]),
                raw=rec,
            ))
        if header is None:
            raise ValueError("M-Pesa statement: header row not found")
        return lines
