"""Deterministic, label-synonym table parser for digital (text-layer) PDFs.

This is the offline baseline and fallback: it reads ruled tables with pdfplumber,
maps header labels through a synonym dictionary and needs no API key. It knows
nothing about specific templates beyond the vocabulary below, but it was written
alongside the synthetic templates, so treat its accuracy on synthetic data as an
upper bound, not as evidence about real-world invoices.
"""
from __future__ import annotations

import re
from io import BytesIO

import pdfplumber

from .base import ExtractionError, ExtractionResult, assemble

LABELS: dict[str, list[str]] = {
    "invoice_number": ["invoice no", "inv #", "invoice number", "bill no", "invoice #", "inv no"],
    "invoice_date": ["invoice date", "date of issue", "bill date", "date"],
    "contract_ref": ["contract ref", "agreement no", "rate agreement", "contract", "contract no", "service contract"],
    "bl_number": ["b/l no", "bill of lading", "bl number", "b/l", "bl no"],
    "origin": ["port of loading", "pol", "origin", "load port"],
    "destination": ["port of discharge", "pod", "destination", "discharge port"],
    "equipment": ["equipment"],
    "container_type": ["container type", "equipment type"],
    "container_count": ["no of containers", "quantity", "number of containers", "containers"],
    "ship_date": ["sailing date", "etd", "vessel sailed", "shipped on", "on board date"],
    "currency": ["currency", "billing currency"],
    "exchange_rate": ["exchange rate", "roe", "rate of exchange"],
    "equipment_out": ["equipment out", "gate out (empty)", "container pick-up", "empty release"],
    "equipment_in": ["equipment returned", "gate in (empty)", "container return", "empty return"],
    "discharge_date": ["discharge date", "vessel discharge", "vessel arrival", "discharged"],
    "pickup_date": ["delivery date", "gate out (full)", "cargo delivered", "collected"],
    "subtotal": ["subtotal", "net amount", "sub total", "total excl tax"],
    "total": ["total amount due", "invoice total", "amount payable", "total incl tax", "total due", "grand total"],
}
_LOOKUP = {syn: f for f, syns in LABELS.items() for syn in syns}

COLUMNS: dict[str, list[str]] = {
    "line_no": ["#", "pos", "no", "sr"],
    "charge_code": ["code", "charge code"],
    "description": ["description", "charge description", "charge", "particulars"],
    "quantity": ["qty", "units", "quantity", "basis"],
    "unit_rate": ["rate", "unit price", "unit rate", "price"],
    "amount": ["amount", "total", "line total"],
}
_COL_LOOKUP = {syn: f for f, syns in COLUMNS.items() for syn in syns}
_TAX = re.compile(r"\b(igst|cgst|sgst|gst|vat|tax)\b", re.I)


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[.:]", "", (s or "").lower())).strip()


def pdf_has_text(pdf_bytes: bytes) -> bool:
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        return sum(len((p.extract_text() or "").strip()) for p in pdf.pages) > 40


def _line_header(row: list) -> dict[int, str] | None:
    cols = {i: _COL_LOOKUP.get(_norm(c)) for i, c in enumerate(row)}
    cols = {i: f for i, f in cols.items() if f}
    fields = set(cols.values())
    return cols if {"description", "amount"} <= fields and ("unit_rate" in fields or "quantity" in fields) else None


def extract_raw(pdf_bytes: bytes) -> dict:
    raw: dict = {"lines": []}
    with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
        tables = [t for p in pdf.pages for t in p.extract_tables()]
    if len(text.strip()) < 40:
        raise ExtractionError("No text layer (scanned document?)")
    raw["carrier"] = next((ln.strip() for ln in text.splitlines() if ln.strip()), None)

    for t in tables:
        if not t:
            continue
        cols = _line_header(t[0])
        if cols:
            for row in t[1:]:
                if _line_header(row):  # repeated header on a continuation page
                    continue
                rec = {f: (row[i] or "").strip() for i, f in cols.items() if i < len(row)}
                if not rec.get("description") and not rec.get("amount"):
                    continue
                rec.pop("line_no", None)
                raw["lines"].append(rec)
            continue
        for row in t:
            cells = [(c or "").strip() for c in row]
            for i in range(len(cells) - 1):
                key = _norm(cells[i])
                if not key:
                    continue
                field = _LOOKUP.get(key)
                if field and field not in raw:
                    raw[field] = cells[i + 1]
                elif _TAX.search(key) and "tax_amount" not in raw:
                    raw["tax_amount"] = cells[i + 1]
                    m = re.search(r"([\d.]+)\s*%", cells[i])
                    if m:
                        raw["tax_rate"] = m.group(1)
    for l in raw["lines"]:  # "2 x DAY" -> "2"
        m = re.match(r"\s*([\d.,]+)", l.get("quantity") or "")
        if m:
            l["quantity"] = m.group(1)
    return raw


class HeuristicExtractor:
    name = "heuristic"

    def extract(self, pdf_bytes: bytes) -> ExtractionResult:
        raw = extract_raw(pdf_bytes)
        inv, notes = assemble(raw)
        return ExtractionResult(invoice=inv, method=self.name, raw=raw, notes=notes)
