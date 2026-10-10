"""Shared extraction plumbing: raw field dict -> validated Invoice + per-field confidence.

Both extractors (layout heuristic and Gemini) produce the same raw dict shape, so
validation, normalization and confidence scoring live in one place.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from ..models import ChargeType, Invoice, InvoiceLine
from ..normalize import (
    map_charge, normalize_container_type, normalize_port, parse_date, parse_decimal,
)

REQUIRED = ["invoice_number", "carrier", "invoice_date", "bl_number", "origin", "destination",
            "container_type", "container_count", "ship_date", "currency", "subtotal", "total"]


class ExtractionError(Exception):
    def __init__(self, message: str, raw: dict | None = None):
        super().__init__(message)
        self.raw = raw or {}


@dataclass
class ExtractionResult:
    invoice: Invoice
    method: str
    raw: dict
    notes: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    attempts: int = 1


def _exchange_rate(text) -> Decimal | None:
    if text is None:
        return None
    s = str(text)
    m = re.search(r"=\s*([\d,]+\.?\d*)", s)
    return parse_decimal(m.group(1) if m else s)


def _raw_for(raw: dict, field: str):
    if field in ("container_type", "container_count") and raw.get("equipment"):
        return raw.get("equipment")
    return raw.get(field)


# (earlier, later) pairs that hold for any shipment. A misread or swapped date usually breaks one,
# and D&D charges are computed from these dates, so a violation must not turn into a dispute.
_DATE_ORDER = [
    ("equipment_out", "equipment_in", "empty container returned before it was released"),
    ("discharge_date", "pickup_date", "full container left the port before it was discharged"),
    ("ship_date", "discharge_date", "container discharged before the vessel sailed"),
    ("equipment_in", "invoice_date", "detention ends after the invoice date"),
    ("pickup_date", "invoice_date", "demurrage ends after the invoice date"),
]
IMPLAUSIBLE_CONF = 0.5


def _check_date_order(out: dict, conf: dict, notes: list[str]) -> None:
    for first, second, why in _DATE_ORDER:
        a, b = out.get(first), out.get(second)
        if a and b and b < a:
            for f in (first, second):
                conf[f] = min(conf.get(f, 1.0), IMPLAUSIBLE_CONF)
            notes.append(f"Implausible dates: {why} ({first} {a}, {second} {b}). Check them against the document.")


def assemble(raw: dict, charge_mapper=None) -> tuple[Invoice, list[str]]:
    """Validate and normalize a raw extraction. Raises ExtractionError if unusable.

    `charge_mapper(descriptions) -> list[(ChargeType, conf)]` is an optional fallback
    (e.g. the LLM) for descriptions the deterministic mapper does not recognise.
    """
    notes: list[str] = []
    conf: dict[str, float] = {}
    out: dict = {}

    def put(name: str, value, required: bool = True):
        out[name] = value
        if value is None:
            if required:
                conf[name] = 0.0
                notes.append(f"Field '{name}' missing or unparseable (raw: {raw.get(name)!r}).")
        else:
            conf[name] = 1.0

    put("invoice_number", (raw.get("invoice_number") or "").strip() or None)
    put("carrier", (raw.get("carrier") or "").strip() or None)
    put("invoice_date", parse_date(raw.get("invoice_date")))
    put("contract_ref", (raw.get("contract_ref") or "").strip() or None, required=False)
    put("bl_number", (raw.get("bl_number") or "").strip() or None)
    put("origin", normalize_port(raw.get("origin")))
    put("destination", normalize_port(raw.get("destination")))

    ctype, count = raw.get("container_type"), raw.get("container_count")
    if raw.get("equipment"):  # "2 x 40HC"
        m = re.match(r"\s*(\d+)\s*[xX×]\s*(.+)", str(raw["equipment"]))
        if m:
            count, ctype = m.group(1), m.group(2)
    put("container_type", normalize_container_type(ctype))
    cnt = parse_decimal(count)
    put("container_count", int(cnt) if cnt is not None and cnt == cnt.to_integral() and cnt > 0 else None)
    put("ship_date", parse_date(raw.get("ship_date")))
    ccy = (raw.get("currency") or "").strip().upper()[:3] or None
    put("currency", ccy if ccy and ccy.isalpha() else None)
    put("exchange_rate", _exchange_rate(raw.get("exchange_rate")), required=ccy not in (None, "USD"))
    for d in ("equipment_out", "equipment_in", "discharge_date", "pickup_date"):
        put(d, parse_date(raw.get(d)), required=False)
    put("subtotal", parse_decimal(raw.get("subtotal")))
    put("total", parse_decimal(raw.get("total")))
    tax_amount = parse_decimal(raw.get("tax_amount"))
    put("tax_amount", tax_amount if tax_amount is not None else Decimal("0"), required=False)
    tax_rate = parse_decimal(raw.get("tax_rate"))
    if tax_rate is not None and tax_rate > 1:
        tax_rate = tax_rate / 100
    out["tax_rate"] = tax_rate

    lines: list[InvoiceLine] = []
    bad_lines = 0
    raw_lines = raw.get("lines") or []
    mapped = [map_charge(str(l.get("description") or ""), l.get("charge_code")) for l in raw_lines]
    unknown = [i for i, (ct, _) in enumerate(mapped) if ct == ChargeType.UNKNOWN]
    if unknown and charge_mapper:
        for i, res in zip(unknown, charge_mapper([str(raw_lines[i].get("description")) for i in unknown])):
            mapped[i] = res
    for i, (l, (ct, mconf)) in enumerate(zip(raw_lines, mapped), 1):
        qty, rate, amt = (parse_decimal(l.get(k)) for k in ("quantity", "unit_rate", "amount"))
        if None in (qty, rate, amt):
            bad_lines += 1
            notes.append(f"Line {i} could not be parsed: {l!r}")
            continue
        lines.append(InvoiceLine(line_no=i, description=str(l.get("description") or "").strip(),
                                 charge_code=(l.get("charge_code") or None), charge_type=ct,
                                 mapping_confidence=mconf, quantity=qty, unit_rate=rate, amount=amt))
    if not lines:
        conf["lines"] = 0.0
        notes.append("No invoice lines extracted.")
    else:
        conf["lines"] = 1.0 if bad_lines == 0 else 0.5

    missing = [f for f in REQUIRED if out.get(f) is None]
    if missing or not lines:
        # Name what the extractor actually returned, so a reviewer (or an eval) can see why.
        got = ", ".join(f"{f}={_raw_for(raw, f)!r}" for f in missing)
        raise ExtractionError(f"Required fields missing: {missing or ['lines']}" + (f" (extracted: {got})" if got else ""), raw)

    _check_date_order(out, conf, notes)
    inv = Invoice(**{k: v for k, v in out.items()}, lines=lines, field_confidence=conf)
    return inv, notes
