"""LLM extraction with Gemini. Reads the PDF directly, so scanned (image-only) files work too.

The LLM only transcribes. It is told not to compute, correct or judge anything;
arithmetic and contract checks happen later in the rule engine.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..llm import GeminiClient, Usage, pdf_part
from ..models import ChargeType
from .base import ExtractionError, ExtractionResult, assemble


class LLMLine(BaseModel):
    description: str
    charge_code: str | None = None
    quantity: float
    unit_rate: float
    amount: float


class LLMInvoice(BaseModel):
    carrier: str | None = Field(None, description="Issuing carrier company name")
    invoice_number: str | None = None
    invoice_date: str | None = Field(None, description="YYYY-MM-DD")
    contract_ref: str | None = Field(None, description="Service contract / rate agreement reference")
    bl_number: str | None = Field(None, description="Bill of lading number")
    origin: str | None = Field(None, description="Port of loading, include UN/LOCODE if printed")
    destination: str | None = Field(None, description="Port of discharge, include UN/LOCODE if printed")
    container_type: str | None = Field(None, description="One of 20GP, 40GP, 40HC")
    container_count: int | None = None
    ship_date: str | None = Field(None, description="Sailing / ETD / shipped-on date, YYYY-MM-DD")
    currency: str | None = Field(None, description="ISO currency code of the invoice amounts")
    exchange_rate: float | None = Field(None, description="Units of invoice currency per 1 USD, if printed")
    equipment_out: str | None = Field(None, description="Empty container gate-out / release / pick-up date, YYYY-MM-DD")
    equipment_in: str | None = Field(None, description="Empty container return / gate-in date, YYYY-MM-DD")
    discharge_date: str | None = Field(None, description="Vessel discharge / arrival date, YYYY-MM-DD")
    pickup_date: str | None = Field(None, description="Full container delivery / collection date, YYYY-MM-DD")
    lines: list[LLMLine] = Field(default_factory=list)
    subtotal: float | None = None
    tax_rate_percent: float | None = None
    tax_amount: float | None = None
    total: float | None = None


SYSTEM = """You transcribe freight invoices into JSON. Copy values exactly as printed.
Rules: do not calculate, correct, round or infer missing values - use null if a field is absent.
Keep every charge line in printed order, including lines that look duplicated.
Quantities are the printed quantity/units/basis count. Amounts are numbers without currency or
thousands separators. Dates must be converted to YYYY-MM-DD (printed dd/mm/yyyy is day-first)."""


class ChargeMapping(BaseModel):
    charge_types: list[ChargeType]


def llm_charge_mapper(client: GeminiClient, usage: Usage):
    def mapper(descriptions: list[str]):
        prompt = ("Map each freight invoice charge description to one standard charge type. "
                  "Use UNKNOWN if unsure.\n" + "\n".join(f"{i + 1}. {d}" for i, d in enumerate(descriptions)))
        res = client.structured([prompt], ChargeMapping, "You classify freight charges.", usage)
        out = res.charge_types + [ChargeType.UNKNOWN] * (len(descriptions) - len(res.charge_types))
        # LLM-mapped types get lower confidence than deterministic matches; < 0.8 routes to review.
        return [(ct, 0.0 if ct == ChargeType.UNKNOWN else 0.85) for ct in out[: len(descriptions)]]
    return mapper


class GeminiExtractor:
    name = "gemini"

    def __init__(self, client: GeminiClient | None = None):
        self.client = client or GeminiClient()

    def extract(self, pdf_bytes: bytes) -> ExtractionResult:
        usage = Usage()
        try:
            data = self.client.structured([pdf_part(pdf_bytes), "Extract this invoice."], LLMInvoice, SYSTEM, usage)
        except ValueError as e:
            raise ExtractionError(str(e)) from e
        raw = data.model_dump()
        raw["tax_rate"] = raw.pop("tax_rate_percent")
        try:
            inv, notes = assemble(raw, charge_mapper=llm_charge_mapper(self.client, usage))
        except ExtractionError as e:
            e.raw = raw
            raise
        return ExtractionResult(invoice=inv, method=f"gemini:{self.client.model}", raw=raw, notes=notes,
                                input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                                cost_usd=usage.cost_usd, attempts=usage.calls)
