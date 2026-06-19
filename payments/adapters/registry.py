from .mpesa_statement import MpesaStatementAdapter
from .paystack_settlement import PaystackSettlementAdapter

_ADAPTERS = {
    "mpesa": MpesaStatementAdapter,
    "paystack": PaystackSettlementAdapter,
}

def get_adapter(name: str):
    try:
        return _ADAPTERS[name]()
    except KeyError:
        raise KeyError(f"Unknown adapter: {name!r}")
