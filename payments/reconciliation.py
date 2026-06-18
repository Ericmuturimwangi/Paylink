from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db.models import Sum
from django.utils import timezone

from .models import (
    Payment, SettlementRecord, SettlementStatus, LedgerEntry, LedgerSide, Account
)

from .states import PaymentStatus
from .ledger import post_balanced, CLEARING


@dataclass
class SettlementLine:
    txn_ref: str
    gross_minor: int
    fee_minor: int
    net_minor: int
    currency: str
    settled_at: datetime
    raw: dict = field(default_factory=dict)

@dataclass
class ReconciliationReport:
    provider: str
    earned_posted: int = 0
    matched: int = 0 
    amount_mismatches: list = field(default_factory=list)
    settled_without_book: list = field(default_factory=list)
    paid_without_settlement: list = field(default_factory=list)
    clearing_balance_minor: int = 0


class ReconciliationService:

    def ingest(self, provider: str, lines) -> int:

        added = 0
        for line in lines:
            if line.gross_minor != line.net_minor + line.fee_minor:
                raise ValueError(
                    f"{line.txn_ref}: gross{line.gross_minor} != net {line.net_minor} + fee {line.fee_minor}"
                )
            _, created = SettlementRecord.objects.get_or_create(
                provider = provider, txn_ref =line.txn_ref,
                defaults = dict(
                    gross_minor = line.gross_minor, fee_minor = line.fee_minor,
                    net_minor = line.net_minor, currency= line.currency,
                    settled_at = line.settled_at, raw=line.raw,
                ),
            )

            added += int(created)
        return added

    def reconcile(self, provider: str, *, unsettled_grace=timedelta(days=2)) -> ReconciliationReport:
        report = ReconciliationReport(provider=provider)
        clearing = CLEARING[provider]
        paid = list(Payment.objects.filter(provider=provider, status=PaymentStatus.PAID.value))

        for p in paid:
            if not LedgerEntry.objects.filter(payment=p, purpose="earned").exists():
                post_balanced(
                    purpose="earned", currency=p.currency,
                    legs=[(clearing, LedgerSide.DEBIT, p.amount_minor),
                        (Account.REVENUE, LedgerSide.CREDIT, p.amount_minor)
                    ],
                    payment=p, 
                )
                report.earned_posted +=1


        
        for s in SettlementRecord.objects.filter(provider=provider, status=SettlementStatus.UNMATCHED):
            p = self._book_match(provider, s.txn_ref)
            if p is None:
                s.status = SettlementStatus.NO_BOOK_ENTRY
                s.save(update_fields=["status"])
                report.settled_without_book.append(s.txn_ref)

                continue
            if p.amount_minor != s.gross_minor:
                s.status = SettlementStatus.AMOUNT_MISMATCH
                s.payment = p
                s.save(update_fields = ["status", "payment"])
                report.amount_mismatches.append((s.txn_ref, p.amount_minor, s.gross_minor))
                continue
                
            if not LedgerEntry.objects.filter(payment=p, purpose="settled").exists():
                post_balanced(
                    purpose="settled", currency=s.currency,
                    legs=[(Account.BANK, LedgerSide.DEBIT, s.net_minor),
                            (Account.FEES, LedgerSide.DEBIT, s.fee_minor),
                            (clearing, LedgerSide.CREDIT, s.gross_minor)],
                    payment = p, settlement=s,

                )

            s.status = SettlementStatus.MATCHED
            s.payment = p 
            s.save(update_fields=["status", "payment"])
            report.matched += 1

        cutoff = timezone.now() - unsettled_grace
        for p in paid:
            has_any_settlement = SettlementRecord.objects.filter(payment=p).exists()
            if not has_any_settlement and p.created_at < cutoff:
                report.paid_without_settlement.append(str(p.id))

        report.clearing_balance_minor = self.clearing_balance(provider)
        return report

    def clearing_balance(self, provider: str) -> int:
        clearing = CLEARING[provider]
        qs = LedgerEntry.objects.filter(account=clearing)
        dr = qs.filter(side=LedgerSide.DEBIT).aggregate(s=Sum("amount_minor"))["s"] or 0
        cr = qs.filter(side=LedgerSide.CREDIT).aggregate(s=Sum("amount_minor"))["s"] or 0
        return dr -cr


    def summary(self, provider: str) -> dict:

        return {
            "provider": provider,
            "clearing_balance_minor": self.clearing_balance(provider),
            "unmatched_settlements": SettlementRecord.objects.filter(
                provider=provider, status=SettlementStatus.UNMATCHED
            ).count(),
            "settled_without_book": SettlementStatus.objects.filter(
                provider=provider, status=SettlementStatus.NO_BOOK_ENTRY
            ).count(),
            "amount_mismatches": SettlementRecord.objects.filter(provider=provider, status=SettlementStatus.AMOUNT_MISMATCH).count(),
        }

    @staticmethod
    def _book_match(provider: str, txn_ref: str):

        field = "provider_receipt" if provider == "mpesa" else "provider_reference"
        return Payment.objects.filter(
            provider=provider, status=PaymentStatus.PAID.value, **{field: txn_ref}
        ).first()

