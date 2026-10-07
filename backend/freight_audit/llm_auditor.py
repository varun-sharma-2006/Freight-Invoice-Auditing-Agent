"""Ablation baseline (a): the LLM does everything - reads the PDF and judges it against the contract.

Used only by the eval harness to compare against the hybrid design. It gets the
same inputs as the hybrid pipeline: the PDF, the contract and the prior invoices.
"""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

from .llm import GeminiClient, Usage, pdf_part
from .models import Contract, ErrorType, Evidence, Finding
from .rules import PriorInvoice


class LLMFinding(BaseModel):
    error_type: ErrorType
    line_no: int | None = Field(None, description="1-based position of the charge line in the table; null for invoice-level issues")
    overcharge: float = Field(description="Overcharge in the contract currency")
    explanation: str


class LLMAudit(BaseModel):
    findings: list[LLMFinding]


SYSTEM = """You are a freight invoice auditor. Compare the invoice against the contract and list every overcharge.
Error types:
- wrong_rate: unit rate above the contract rate for the lane, container type and ship date
- expired_rate: billed the rate of a different validity period than the ship date falls in
- duplicate_line: the same charge billed twice on this invoice (flag the repeated line)
- duplicate_invoice: this shipment was already invoiced (see prior invoices)
- unauthorized_charge: a charge type not permitted by the contract
- calculation_error: line amount != quantity x rate, or total != subtotal + tax (invoice-level: line_no null)
- detention_demurrage: detention/demurrage days or daily rate wrong after the contract's free days
  (detention = equipment return minus equipment out; demurrage = pickup minus discharge)
- currency_tax: exchange rate above the agreed rate, or tax above the contract tax rate (invoice-level)
Contract rates are in the contract currency; convert invoice amounts using the invoice's exchange rate.
Only report overcharges. Report nothing for a clean invoice. Line numbers count charge rows from 1."""


def llm_audit(pdf_bytes: bytes, contract: Contract, history: list[PriorInvoice],
              client: GeminiClient | None = None) -> tuple[list[Finding], Usage]:
    client = client or GeminiClient()
    usage = Usage()
    prior = "\n".join(f"- {p.invoice_number} | carrier {p.carrier} | B/L {p.bl_number} | total {p.total} {p.currency}"
                      for p in history) or "(none)"
    prompt = (f"CONTRACT (JSON):\n{contract.model_dump_json()}\n\nPRIOR INVOICES ALREADY PROCESSED:\n{prior}\n\n"
              "Audit the attached invoice.")
    res = client.structured([pdf_part(pdf_bytes), prompt], LLMAudit, SYSTEM, usage)
    findings = [Finding(
        error_type=f.error_type, rule_id="llm_only", line_no=f.line_no,
        difference=Decimal(str(round(f.overcharge, 2))), currency=contract.currency, confidence=1.0,
        message=f.explanation, evidence=Evidence(contract_clause="(LLM judgement)", invoice_text="(LLM judgement)"))
        for f in res.findings]
    return findings, usage
