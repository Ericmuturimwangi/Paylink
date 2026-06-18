from __future__ import annotations
import uuid

from django.db import transaction
from .models import LedgerEntry, LedgerSide, Account

CLEARING ={
    "mpesa": Account.MPESA_CLEARING, 
    "paystack": Account.PAYSTACK_CLEARING,
}

def post_balanced(*, purpose: str, currency: str, legs, payment=None, settlement=None):

    legs = list(legs)
    debits = sum(a for _, s, a in legs if s == LedgerSide.DEBIT)
    credits = sum(a for _, s, a in legs if s == LedgerSide.CREDIT)

    if debits != credits:
        raise ValueError(f"unbalanced posting: DR {debits} != CR {credits}")
    if debits == 0:
        raise ValueError("refusing to post a zero-value group")

    
    group = uuid.uuid4()
    with transaction.atomic():
        for account, side, amount in legs:
            LedgerEntry.objects.create(
                group=group, purpose=purpose, account=account, side=side,
                amount_minor = amount, currency=currency,
                payment=payment, settlement=settlement,
            )
    return group
    