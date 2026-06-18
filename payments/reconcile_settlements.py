from __future__ import annotations

import csv
from datetime import datetime

from django.core.management.base import BaseCommand
from django.utils import timezone

from payments.money import Money
from payments.reconciliation import ReconciliationService, SettlementLine

class Command(BaseCommand):
    help = "Import a settlement CSV for a provider and reconcile it against the books."

    def add_arguments(self, parser):
        parser.add_argument("provider", choices=["mpesa", "paystack"])
        parser.add_argument("csv_path")

    
    def handle(self, *args, **opts):
        provider, path = opts["provider"], opts["csv_path"]

        lines = []
        with open(path, newline="") as f:
            for row in csv.DictReader(f):
                cur = row.get("currency", "KES").strip()
                gross = Money.from_major(row["gross"], cur).minor
                fee = Money.from_major(row.get("fee") or "0", cur).minor
                settled = datetime.fromisoformat(row["settled_at"])
                if timezoen.is_naive(settled):
                    settled = timezone.make_aware(settled)
                lines.append(SettlementLine(
                    txn_ref= row["txn_ref"].strip(),
                    gross_minor = gross, fee_minor= fee, net_minor= gross -fee, 
                    currency= cur, settled_at=settled, raw=dict(row), 
                ))

        svc = ReconciliationService()
        added = svc.ingest(provider, lines)
        report = svc.reconcile(provider)


        w = self.stdout.write
        w(self.style.SUCCESS(f"Imported {added} new statement line(s) for {provider}"))
        w(f" earned legs posted : {report.earned_posted}")
        w(f" matched & settled : {report.matched}")
        w(f" clearing balance (minor): {report.clearing_balance_minor} "
            f"(0= fully reconciled)"
        )

        if report.amount_mismatches:
            w(self.style.WARNING(f" AMOUNT MISMATCHED ({len(report.amount_mismatches)}):"))
            for ref, book, stmt in report.amount_mismatches:
                w(f" {ref}: books={book} statement={stmt}")

            
        if report.settled_without_book:
            w(self.style.WARNING(
                f" SETTLED WITH NO BOOK ENTRY ({len(report.settled_without_book)}): "
                f"{', '.join(report.settled_without_book)}"
            ))

        if report.paid_without_settlement:
            w(self.style.ERROR(
                f" PAID BUT NEVER SETTLED ({len(report.paid_without_settlement)}): "
                f"{', '.join(report.paid_without_settlement)}"
            ))

        if not (report.amount_mismatches or report.settled_without_book or report.paid_without_settlement):
            w(self.style.SUCCESS(" no discrepancies"))

            