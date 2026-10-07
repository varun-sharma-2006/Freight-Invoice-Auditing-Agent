"""Dispute email drafting.

The LLM only writes prose. Every money figure must come from the rule-engine
findings: after drafting, all numbers in the email are checked against the
figures we supplied, and if the model invented or altered one, the draft is
discarded in favour of the deterministic template.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .models import ErrorType

TITLES = {
    ErrorType.WRONG_RATE.value: "Rate above contract",
    ErrorType.EXPIRED_RATE.value: "Rate from an expired validity period",
    ErrorType.DUPLICATE_LINE.value: "Duplicate charge line",
    ErrorType.DUPLICATE_INVOICE.value: "Duplicate invoice",
    ErrorType.UNAUTHORIZED_CHARGE.value: "Charge not permitted by contract",
    ErrorType.CALCULATION_ERROR.value: "Calculation error",
    ErrorType.DETENTION_DEMURRAGE.value: "Detention / demurrage miscalculated",
    ErrorType.CURRENCY_TAX.value: "Exchange rate / tax error",
}


@dataclass
class DraftFinding:
    error_type: str
    line_no: int | None
    expected: Decimal | None
    billed: Decimal | None
    difference: Decimal
    currency: str
    message: str
    contract_clause: str
    invoice_text: str


@dataclass
class DraftContext:
    carrier: str
    invoice_number: str
    invoice_date: str
    bl_number: str
    contract_id: str
    findings: list[DraftFinding]
    sender: str = "Freight Audit Team"

    @property
    def total(self) -> Decimal:
        return sum((f.difference for f in self.findings), Decimal(0))

    @property
    def currency(self) -> str:
        return self.findings[0].currency if self.findings else "USD"


def m(x: Decimal | None) -> str:
    return "n/a" if x is None else f"{x:,.2f}"


def subject(ctx: DraftContext) -> str:
    return (f"Invoice dispute: {ctx.invoice_number} (B/L {ctx.bl_number}) - "
            f"{ctx.currency} {m(ctx.total)} overbilled")


def template_body(ctx: DraftContext) -> str:
    out = [f"Dear {ctx.carrier} Billing Team,", "",
           f"We have reviewed invoice {ctx.invoice_number} dated {ctx.invoice_date} for B/L {ctx.bl_number} "
           f"against service contract {ctx.contract_id} and found the following discrepancies:", ""]
    for i, f in enumerate(ctx.findings, 1):
        where = f"line {f.line_no}" if f.line_no else "invoice level"
        out += [f"{i}. {TITLES.get(f.error_type, f.error_type)} ({where}): {ctx.currency} {m(f.difference)}",
                f"   {f.message}",
                f"   Invoice: {f.invoice_text}",
                f"   Contract: {f.contract_clause}", ""]
    out += [f"Total amount disputed: {ctx.currency} {m(ctx.total)}.", "",
            "Please issue a credit note or a corrected invoice for the amounts above. We will settle the undisputed "
            "balance in line with our payment terms.", "", "Kind regards,", ctx.sender]
    return "\n".join(out)


_NUM = re.compile(r"\d[\d,]*\.\d{2}\b")


def allowed_figures(ctx: DraftContext) -> set[str]:
    figs = {m(ctx.total)}
    for f in ctx.findings:
        figs |= {m(f.difference), m(f.expected), m(f.billed)}
        figs |= set(_NUM.findall(f.message + " " + f.invoice_text + " " + f.contract_clause))
    return {x.replace(",", "") for x in figs}


def unsupported_figures(body: str, ctx: DraftContext) -> list[str]:
    ok = allowed_figures(ctx)
    return [n for n in _NUM.findall(body) if n.replace(",", "") not in ok]


LLM_SYSTEM = """You write concise, professional, firm-but-polite freight invoice dispute emails.
Use ONLY the facts and figures provided. Never compute new numbers or change any figure.
Cite the evidence for each item (invoice line and contract clause). No placeholders. Plain text only."""


def llm_body(ctx: DraftContext, client, usage) -> str:
    facts = template_body(ctx)
    return client.text([f"Rewrite this dispute as a clear email body. Keep every figure exactly.\n\n{facts}"],
                       LLM_SYSTEM, usage).strip()


def draft(ctx: DraftContext, client=None) -> tuple[str, str, str, dict]:
    """Return (subject, body, drafted_by, meta)."""
    if client is not None:
        from .llm import Usage

        usage = Usage()
        try:
            body = llm_body(ctx, client, usage)
            bad = unsupported_figures(body, ctx)
            if body and not bad:
                return subject(ctx), body, f"llm:{client.model}", dict(cost_usd=usage.cost_usd)
            meta = dict(fallback_reason=f"LLM draft contained unsupported figures {bad[:5]}")
        except Exception as e:  # network / quota: fall back, never block the reviewer
            meta = dict(fallback_reason=f"LLM unavailable: {type(e).__name__}")
        return subject(ctx), template_body(ctx), "template", meta
    return subject(ctx), template_body(ctx), "template", {}
