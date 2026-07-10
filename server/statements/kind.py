"""Transaction-kind classification (port of site kind.ts).

Card statements mix real spend with payments, fees, interest, and cash
advances; only purchases/refunds may reach categorization, or a $2,000
"PAYMENT THANK YOU" would inflate a spend bucket. Classification layers:
explicit type columns (CSV Type, OFX TRNTYPE) first, then descriptor
patterns — a DEBIT row reading "ANNUAL FEE" is still a fee.
"""

from typing import Optional

PAYMENT_PATTERNS = [
    "PAYMENT THANK YOU", "PAYMENT - THANK YOU", "THANK YOU FOR YOUR PAYMENT",
    "AUTOPAY", "AUTO-PAY", "AUTOMATIC PAYMENT", "ONLINE PAYMENT", "ACH PAYMENT",
    "MOBILE PAYMENT", "PAYMENT RECEIVED", "ELECTRONIC PAYMENT", "E-PAYMENT",
    "DIRECTPAY", "ONLINE TRANSFER TO", "PAYMENT FROM CHK", "PYMT",
]
INTEREST_PATTERNS = [
    "INTEREST CHARGE", "PURCHASE INTEREST", "INTEREST CHARGED", "FINANCE CHARGE",
]
FEE_PATTERNS = [
    "ANNUAL FEE", "ANNUAL MEMBERSHIP FEE", "MEMBERSHIP FEE", "LATE FEE",
    "LATE PAYMENT FEE", "FOREIGN TRANSACTION FEE", "RETURNED PAYMENT FEE",
    "CASH ADVANCE FEE", "OVERLIMIT FEE",
]
TRANSFER_PATTERNS = ["BALANCE TRANSFER", "CASH ADVANCE"]

# CSV Type-column values (Chase/Apple-style), lowercased.
CSV_TYPE_KINDS = {
    "sale": "purchase",
    "purchase": "purchase",
    "return": "refund",
    "refund": "refund",
    "payment": "payment",
    "fee": "fee",
    "interest": "interest",
    "adjustment": "refund",
}

# OFX <TRNTYPE> values. DEBIT/CREDIT/POS stay 'purchase' here — refund vs
# purchase is decided by the normalized sign, and payment-looking CREDITs are
# caught by the descriptor patterns below.
OFX_TYPE_KINDS = {
    "int": "interest",
    "fee": "fee",
    "srvchg": "fee",
    "xfer": "transfer",
    "payment": "payment",
}


def classify_kind(descriptor: str, csv_type: Optional[str] = None,
                  ofx_type: Optional[str] = None) -> str:
    upper = descriptor.upper()
    # Descriptor patterns win over generic DEBIT/CREDIT typing but lose to an
    # explicit non-purchase column type (an issuer's own "Fee" flag is truth).
    explicit = None
    if csv_type is not None:
        explicit = CSV_TYPE_KINDS.get(csv_type.strip().lower())
    elif ofx_type is not None:
        explicit = OFX_TYPE_KINDS.get(ofx_type.strip().lower())
    if explicit and explicit not in ("purchase", "refund"):
        return explicit

    if upper.strip() == "PAYMENT":  # Bilt prints bare "PAYMENT"
        return "payment"
    if any(p in upper for p in INTEREST_PATTERNS):
        return "interest"
    if any(p in upper for p in FEE_PATTERNS):
        return "fee"
    if any(p in upper for p in TRANSFER_PATTERNS):
        return "transfer"
    if any(p in upper for p in PAYMENT_PATTERNS):
        return "payment"
    return explicit or "purchase"


def refine_refund(kind: str, amount_cents: int) -> str:
    """After sign normalization (spend positive), a negative purchase is a refund."""
    return "refund" if kind == "purchase" and amount_cents < 0 else kind
