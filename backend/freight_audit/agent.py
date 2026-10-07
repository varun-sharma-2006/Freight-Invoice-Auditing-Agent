"""Conversational agent over the audit data, using Gemini function calling.

Tools: get_contract, check_invoice, find_duplicates, draft_dispute. The agent can
explain findings and create a *draft* dispute, but it has no tool to approve or
send - those stay human-only actions in the review UI.
"""
# No `from __future__ import annotations`: Gemini reads the tool signatures at runtime.
import functools
import json
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import InvoiceRow, log_event
from .services import WorkflowError, draft_dispute as _draft, get_contract as _get_contract, llm_client_or_none

SYSTEM = """You are a freight invoice audit assistant. Answer using the tools; never guess figures.
Findings come from a deterministic rule engine - explain them, cite the evidence (invoice line and contract clause),
and do not invent new findings. You may create a dispute DRAFT; a human must approve and send it.
Be concise. Amounts in findings are in the contract currency."""


def _invoice_view(r: InvoiceRow) -> dict:
    return dict(
        id=r.id, invoice_number=r.invoice_number, carrier=r.carrier, bl_number=r.bl_number, status=r.status,
        contract_id=r.contract_id, currency=r.currency, total=str(r.total) if r.total is not None else None,
        review_notes=r.review_notes,
        findings=[dict(id=f.id, type=f.error_type, line_no=f.line_no, expected=None if f.expected is None else f"{f.expected:.2f}", billed=None if f.billed is None else f"{f.billed:.2f}",
                       overcharge=f"{f.difference:.2f}", currency=f.currency, status=f.status, message=f.message,
                       contract_clause=f.contract_clause, invoice_text=f.invoice_text) for f in r.findings])


def make_tools(s: Session, calls: list[dict]):
    def logged(fn):
        @functools.wraps(fn)  # keeps the signature/docstring Gemini turns into a function declaration
        def wrapper(*a, **kw):
            out = fn(*a, **kw)
            calls.append(dict(tool=fn.__name__, args=kw or list(a)))
            return out
        return wrapper

    def get_contract(contract_id: str) -> dict:
        """Get a carrier contract: validity, allowed charges, tax/FX terms and rate table."""
        c = _get_contract(s, contract_id)
        return json.loads(c.model_dump_json()) if c else {"error": f"contract {contract_id} not found"}

    def check_invoice(invoice_id: int) -> dict:
        """Get an invoice's audit result: status, findings with evidence, and review notes."""
        r = s.get(InvoiceRow, invoice_id)
        return _invoice_view(r) if r else {"error": f"invoice {invoice_id} not found"}

    def find_duplicates(invoice_id: int) -> dict:
        """List other invoices from the same carrier with the same invoice number or B/L number."""
        r = s.get(InvoiceRow, invoice_id)
        if not r:
            return {"error": f"invoice {invoice_id} not found"}
        q = select(InvoiceRow).where(InvoiceRow.id != r.id, InvoiceRow.carrier == r.carrier,
                                     (InvoiceRow.invoice_number == r.invoice_number) | (InvoiceRow.bl_number == r.bl_number))
        return {"matches": [dict(id=x.id, invoice_number=x.invoice_number, bl_number=x.bl_number, total=str(x.total),
                                 currency=x.currency) for x in s.scalars(q)]}

    def draft_dispute(invoice_id: int) -> dict:
        """Create or refresh the dispute email DRAFT for an invoice. Does not send anything."""
        try:
            d = _draft(s, invoice_id, actor="agent")
        except WorkflowError as e:
            return {"error": str(e)}
        return dict(dispute_id=d.id, status=d.status, subject=d.subject, amount=str(d.amount), currency=d.currency)

    return [logged(f) for f in (get_contract, check_invoice, find_duplicates, draft_dispute)]


def chat(s: Session, message: str, invoice_id: int | None = None) -> dict:
    calls: list[dict] = []
    tools = make_tools(s, calls)
    client = llm_client_or_none()
    context = f"\n(The user is looking at invoice id {invoice_id}.)" if invoice_id else ""
    if client is not None:
        from google.genai import types

        try:
            session = client.client.chats.create(model=client.model, config=types.GenerateContentConfig(
                system_instruction=SYSTEM, tools=tools, temperature=0.2))
            answer = session.send_message(message + context).text or ""
            log_event(s, "agent", invoice_id or "-", "chat", "agent", question=message[:300], tools=calls)
            return dict(answer=answer, tool_calls=calls, mode=f"llm:{client.model}")
        except Exception as e:
            fallback_reason = f"LLM unavailable ({type(e).__name__}); answered with the offline router."
    else:
        fallback_reason = "No LLM configured; answered with the offline router."
    answer = _offline(message, invoice_id, tools)
    log_event(s, "agent", invoice_id or "-", "chat", "agent_offline", question=message[:300], tools=calls)
    return dict(answer=f"{answer}\n\n_{fallback_reason}_", tool_calls=calls, mode="offline")


def _offline(message: str, invoice_id: int | None, tools) -> str:
    get_contract, check_invoice, find_duplicates, draft_dispute = tools
    low = message.lower()
    m = re.search(r"invoice\s*(?:id\s*)?#?(\d+)", low)
    iid = int(m.group(1)) if m else invoice_id
    if iid is None:
        return "Tell me which invoice (e.g. 'invoice 3') or open one in the UI and ask again."
    if "draft" in low or "dispute" in low:
        r = draft_dispute(invoice_id=iid)
        return r.get("error") or f"Draft dispute #{r['dispute_id']} created: \"{r['subject']}\". Review and approve it in the UI."
    if "duplicate" in low:
        r = find_duplicates(invoice_id=iid)
        if "error" in r:
            return r["error"]
        return ("No other invoices share this invoice number or B/L." if not r["matches"] else
                "Possible duplicates: " + "; ".join(f"#{x['id']} {x['invoice_number']} (B/L {x['bl_number']}, "
                                                     f"{x['currency']} {x['total']})" for x in r["matches"]))
    inv = check_invoice(invoice_id=iid)
    if "error" in inv:
        return inv["error"]
    if "contract" in low and inv.get("contract_id"):
        c = get_contract(contract_id=inv["contract_id"])
        return (f"Contract {c['contract_id']} ({c['carrier']}), valid {c['valid_from']} to {c['valid_to']}. "
                f"Allowed charges: {', '.join(c['allowed_charges'])}.")
    if not inv["findings"]:
        return f"Invoice {inv['invoice_number']} has no findings." + (
            f" Review notes: {'; '.join(inv['review_notes'])}" if inv["review_notes"] else "")
    lines = [f"Invoice {inv['invoice_number']} has {len(inv['findings'])} finding(s):"]
    for f in inv["findings"]:
        where = f"line {f['line_no']}" if f["line_no"] else "invoice level"
        lines.append(f"- {f['type']} ({where}), overcharge {f['currency']} {f['overcharge']}: {f['message']} "
                     f"[evidence: {f['contract_clause']}]")
    return "\n".join(lines)
