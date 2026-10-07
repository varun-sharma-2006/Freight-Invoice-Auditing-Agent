"""Normalization: charge descriptions -> ChargeType, ports, container types, dates, numbers.

Charge mapping is deterministic first (charge codes, then keyword patterns). Only
descriptions that no pattern recognises fall through to the optional LLM mapper
(see extraction/gemini.py); anything still unmapped becomes UNKNOWN and is routed
to human review rather than guessed.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from .models import ChargeType

# Common carrier charge codes.
CHARGE_CODES: dict[str, ChargeType] = {
    "OFR": ChargeType.BASE_FREIGHT, "FRT": ChargeType.BASE_FREIGHT, "BAS": ChargeType.BASE_FREIGHT,
    "BAF": ChargeType.FUEL_SURCHARGE, "FSC": ChargeType.FUEL_SURCHARGE, "BUC": ChargeType.FUEL_SURCHARGE,
    "LSS": ChargeType.FUEL_SURCHARGE,
    "THO": ChargeType.THC_ORIGIN, "OTHC": ChargeType.THC_ORIGIN,
    "THD": ChargeType.THC_DEST, "DTHC": ChargeType.THC_DEST,
    "DOC": ChargeType.DOC_FEE, "BLF": ChargeType.DOC_FEE,
    "ISP": ChargeType.ISPS, "ISPS": ChargeType.ISPS,
    "SEA": ChargeType.SEAL_FEE, "SEAL": ChargeType.SEAL_FEE,
    "DET": ChargeType.DETENTION, "DEM": ChargeType.DEMURRAGE,
    "PSS": ChargeType.PEAK_SEASON, "CGS": ChargeType.CONGESTION, "PCS": ChargeType.CONGESTION,
    "EBS": ChargeType.EMERGENCY_BUNKER, "EBF": ChargeType.EMERGENCY_BUNKER,
    "WRS": ChargeType.WAR_RISK, "CAF": ChargeType.CURRENCY_ADJUSTMENT,
}

# Ordered: more specific patterns first ("emergency bunker" before "bunker").
_PATTERNS: list[tuple[str, ChargeType]] = [
    (r"emergency\s*(bunker|fuel)|\bebs\b|\bebf\b", ChargeType.EMERGENCY_BUNKER),
    (r"peak\s*season|\bpss\b|\bgri\b", ChargeType.PEAK_SEASON),
    (r"congestion|\bpcs\b", ChargeType.CONGESTION),
    (r"war\s*risk|\bwrs\b", ChargeType.WAR_RISK),
    (r"currency\s*adj|\bcaf\b", ChargeType.CURRENCY_ADJUSTMENT),
    (r"bunker|\bbaf\b|fuel|\bfsc\b|low\s*sulph|\blss\b", ChargeType.FUEL_SURCHARGE),
    (r"demurrage|\bdem\b", ChargeType.DEMURRAGE),
    (r"detention|\bdet\b", ChargeType.DETENTION),
    (r"(terminal|thc|hdlg|handling).*(dest|import|pod|discharge)|(dest\w*|import|pod)\b.*(terminal|thc|handling)"
     r"|\bdthc\b|\bthd\b", ChargeType.THC_DEST),
    (r"(terminal|thc|hdlg|handling).*(orig|export|pol|load)|(orig\w*|export|pol)\b.*(terminal|thc|handling)"
     r"|\bothc\b|\btho\b", ChargeType.THC_ORIGIN),
    (r"isps|port\s*security|security\s*(fee|surcharge|charge)", ChargeType.ISPS),
    (r"\bseal\b", ChargeType.SEAL_FEE),
    (r"doc(ument|umentation|s)?\b|b/?l\s*fee|bill\s*of\s*lading\s*fee", ChargeType.DOC_FEE),
    (r"ocean\s*freight|sea\s*freight|basic\s*freight|base\s*(ocean\s*)?(freight|rate)|\bofr\b|freight\s*charge", ChargeType.BASE_FREIGHT),
]


def map_charge(description: str, code: str | None = None) -> tuple[ChargeType, float]:
    """Return (charge_type, confidence). UNKNOWN with 0.0 when nothing matches."""
    if code:
        ct = CHARGE_CODES.get(code.strip().upper())
        if ct:
            return ct, 1.0
    text = description.lower()
    for pattern, ct in _PATTERNS:
        if re.search(pattern, text):
            return ct, 0.95
    return ChargeType.UNKNOWN, 0.0


# ---------------------------------------------------------------- ports & equipment
PORTS: dict[str, str] = {
    "nhava sheva": "INNSA", "jnpt": "INNSA", "mundra": "INMUN", "chennai": "INMAA",
    "rotterdam": "NLRTM", "hamburg": "DEHAM", "jebel ali": "AEJEA", "new york": "USNYC",
    "singapore": "SGSIN", "antwerp": "BEANR", "felixstowe": "GBFXT",
}
PORT_NAMES = {v: k.title() for k, v in PORTS.items() if k != "jnpt"}
PORT_NAMES["INNSA"] = "Nhava Sheva"


def normalize_port(text: str | None) -> str | None:
    if not text:
        return None
    m = re.search(r"\b([A-Z]{2}\s?[A-Z]{3})\b", text)
    if m and m.group(1).replace(" ", "") in PORT_NAMES:
        return m.group(1).replace(" ", "")
    low = text.lower()
    for name, code in PORTS.items():
        if name in low:
            return code
    return None


def normalize_container_type(text: str | None) -> str | None:
    if not text:
        return None
    t = text.upper().replace("'", "").replace("FT", "")
    size = "40" if "40" in t else "20" if "20" in t else None
    if size is None:
        return None
    if re.search(r"HC|HIGH\s*CUBE|HQ", t):
        return "40HC" if size == "40" else None
    return f"{size}GP"


# ---------------------------------------------------------------- scalars
_DATE_FORMATS = ["%Y-%m-%d", "%d-%b-%Y", "%d %b %Y", "%d/%m/%Y", "%d.%m.%Y", "%b %d, %Y", "%d-%m-%Y"]


def parse_date(text: str | None) -> date | None:
    if not text:
        return None
    s = text.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal(text: str | float | int | None) -> Decimal | None:
    if text is None:
        return None
    if isinstance(text, (int, float, Decimal)):
        return Decimal(str(text))
    s = re.sub(r"[^\d.\-]", "", str(text).replace(",", ""))
    if s in ("", "-", ".", "-."):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None
