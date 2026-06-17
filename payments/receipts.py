from __future__ import annotations

import io

from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


from .money import Money

_GREEN = colors.HexColor("#0a7d33")
_GREY = colors.HexColor("#6b7280")
_LINE = colors.HexColor("#e6e6e6")


def render_receipt_pdf(*, receipt_number: str, payment, generated_at) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize = A4,
        topMargin = 25* mm, bottomMargin=20 * mm,
        leftMargin = 20 * mm, rightMargin = 20* mm,
        title = f"Receipt {receipt_number}",
    )

    base = getSampleStyleSheet()
    title = ParagraphStyle("title", parent=base["Title"], fontSize=20, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=base["Normal"], fontSize=10, textColor=_GREY)
    label = ParagraphStyle("label", parent=base["Normal"], fontSize=9, textColor=_GREY)
    value = ParagraphStyle("value", parent=base["Normal"], fontSize=11)
    amount = ParagraphStyle("amount", parent=base["Title"], fontSize=24, textColor=_GREEN)
    paid = ParagraphStyle("paid", parent=base["Normal"], fontSize=11, textColor=_GREEN)


    money = Money(payment.amount_minor, payment.currency)

    story = [
        Paragraph("PAYMENT RECEIPT", title),
        Paragraph(f"Receipt No. {receipt_number}", sub),
        Spacer(1, 16),
        Paragraph(f"{payment.currency} {money.major:.2f}", amount),
        Paragraph(payment.status.upper(), paid),
        Spacer(1, 18)
    ]

    rows = [
        ("Date", generated_at.strftime("%d %b %Y, %H:%M")),
        ("Transaction ID", str(payment.id)),
        ("Provider", payment.provider.upper()),
        ("Provider Receipt", payment.provider_receipt or "-"),
        ("Customer Phone", payment.customer_phone or "-"),
        ("Customer Email", payment.customer_email or "-"),
        ("Description", payment.description or "-"),
        ("Amount", f"{payment.currency} {money.major:.2f}"),
    ]

    table = Table(
        [[Paragraph(k, label), Paragraph(str(v), value)] for k, v in rows],
        colWidths=[45 * mm, 110 * mm],
    )

    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, _LINE),
    ]))

    story.append(table)
    story.append(Spacer(1, 24))
    story.append(Paragraph(
        "This is a computer generated receipt and does not require a signature.", sub
    ))

    doc.build(story)
    return buf.getvalue()



class ReceiptService:
    def get_or_create(self, payment):

        from .models import Receipt, AuditLog, AuditEvent
 
        existing = Receipt.objects.filter(payment=payment).first()
        if existing:
            return existing
 
        number = self._number(payment)
        now = timezone.now()
        pdf_bytes = render_receipt_pdf(receipt_number=number, payment=payment, generated_at=now)
 
        try:
            with transaction.atomic():
                receipt = Receipt(payment=payment, receipt_number=number)
                receipt.pdf.save(f"{number}.pdf", ContentFile(pdf_bytes), save=True)
            AuditLog.record(
                payment=payment, event=AuditEvent.RECEIPT_GENERATED, source="receipt",
                summary=f"receipt {number} generated",
            )
            return receipt
        except IntegrityError:
            # a concurrent caller won the race -> return theirs
            return Receipt.objects.get(payment=payment)
 
    @staticmethod
    def _number(payment) -> str:
        # Readable + unique, NOT gapless. Legally gapless sequential numbering
        # (where required) needs a locked DB counter -> deferred.
        return f"RCP-{timezone.now():%Y%m%d}-{str(payment.id).split('-')[0].upper()}"
