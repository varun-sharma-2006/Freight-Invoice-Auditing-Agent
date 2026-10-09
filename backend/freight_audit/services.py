"""Application service: upload -> extract -> normalize -> audit -> persist, plus the dispute workflow.

Every state change writes an audit event. Re-uploading the same file is a no-op
(idempotent on SHA-256); a *different* file for an already-billed shipment is
caught by the duplicate-invoice rule instead.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from decimal import Decimal
from email.message import EmailMessage

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .db import (
    AllowedChargeRow, ContractRateRow, ContractRow, DisputeRow, FindingRow, InvoiceLineRow, InvoiceRow, log_event,
)
from .drafting import DraftContext, DraftFinding, draft
from .extraction import ExtractionError, extract
from .models import Contract, Invoice
from .rules import PriorInvoice, audit_invoice


class WorkflowError(ValueError):
    pass


def llm_client_or_none():
    if not get_settings().api_key:
        return None
    try:
        from .llm import GeminiClient

        return GeminiClient()
    except Exception:
        return None


# ------------------------------------------------------------------ contracts
def upsert_contract(s: Session, c: Contract, actor: str = "system") -> ContractRow:
    row = s.get(ContractRow, c.contract_id)
    action = "contract_updated" if row else "contract_loaded"
    if row:
        s.delete(row)
        s.flush()
    row = ContractRow(id=c.contract_id, carrier=c.carrier, valid_from=c.valid_from, valid_to=c.valid_to,
                      currency=c.currency, data=c.model_dump(mode="json"))
    row.rates = [ContractRateRow(origin=r.origin, destination=r.destination, container_type=r.container_type,
                                 charge_type=r.charge_type.value, rate=r.rate, unit=r.unit.value, free_days=r.free_days,
                                 valid_from=r.valid_from, valid_to=r.valid_to) for r in c.rates]
    row.allowed = [AllowedChargeRow(charge_type=a.value) for a in c.allowed_charges]
    s.add(row)
    log_event(s, "contract", c.contract_id, action, actor, rates=len(c.rates), carrier=c.carrier)
    return row


def get_contract(s: Session, contract_id: str) -> Contract | None:
    row = s.get(ContractRow, contract_id)
    return Contract.model_validate(row.data) if row else None


def find_contract_for(s: Session, inv: Invoice, explicit: str | None) -> Contract | None:
    for cid in (explicit, inv.contract_ref):
        if cid and (c := get_contract(s, cid)):
            return c
    row = s.scalars(select(ContractRow).where(ContractRow.carrier.ilike(inv.carrier))
                    .order_by(ContractRow.valid_from.desc())).first()
    return Contract.model_validate(row.data) if row else None


# ------------------------------------------------------------------ invoices
def history_for(s: Session, carrier: str, exclude_id: int | None = None) -> list[PriorInvoice]:
    q = select(InvoiceRow).where(InvoiceRow.carrier.ilike(carrier), InvoiceRow.invoice_number.is_not(None))
    if exclude_id:
        q = q.where(InvoiceRow.id != exclude_id)
    return [PriorInvoice(r.id, r.invoice_number, r.carrier, r.bl_number, r.total, r.currency)
            for r in s.scalars(q.order_by(InvoiceRow.id))]


def process_invoice(s: Session, pdf: bytes, filename: str, contract_id: str | None = None,
                    extractor: str | None = None, actor: str = "system") -> tuple[InvoiceRow, bool]:
    """Returns (invoice_row, created). created=False means this exact file was already processed."""
    sha = hashlib.sha256(pdf).hexdigest()
    existing = s.scalar(select(InvoiceRow).where(InvoiceRow.file_sha256 == sha))
    if existing:
        log_event(s, "invoice", existing.id, "upload_deduplicated", actor, filename=filename)
        return existing, False

    settings = get_settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{sha[:16]}.pdf"
    path.write_bytes(pdf)
    row = InvoiceRow(file_sha256=sha, filename=filename, source_path=str(path), file_bytes=pdf,
                     status="processing", review_notes=[])
    s.add(row)
    s.flush()
    log_event(s, "invoice", row.id, "uploaded", actor, filename=filename, sha256=sha)

    t0 = time.perf_counter()
    try:
        res = extract(pdf, mode=extractor)
    except Exception as e:  # extraction failure is never fatal: route to a human
        row.status = "needs_review"
        row.review_notes = [f"Extraction failed: {e}"]
        row.latency_s = time.perf_counter() - t0
        log_event(s, "invoice", row.id, "extraction_failed", "system", error=str(e)[:500])
        return row, True

    inv = res.invoice
    row.extraction_method, row.cost_usd = res.method, res.cost_usd
    row.carrier, row.invoice_number, row.invoice_date = inv.carrier, inv.invoice_number, inv.invoice_date
    row.bl_number, row.currency, row.total = inv.bl_number, inv.currency, inv.total
    row.data = inv.model_dump(mode="json")
    row.lines = [InvoiceLineRow(line_no=l.line_no, description=l.description, charge_type=l.charge_type.value,
                                mapping_confidence=l.mapping_confidence, quantity=l.quantity, unit_rate=l.unit_rate,
                                amount=l.amount) for l in inv.lines]
    log_event(s, "invoice", row.id, "extracted", "system", method=res.method, lines=len(inv.lines),
              cost_usd=res.cost_usd, notes=res.notes)

    notes = list(res.notes)
    contract = find_contract_for(s, inv, contract_id)
    if contract is None:
        notes.append(f"No contract found for carrier '{inv.carrier}' / ref '{inv.contract_ref}'.")
        row.status = "needs_review"
    else:
        row.contract_id = contract.contract_id
        result = audit_invoice(inv, contract, history_for(s, inv.carrier, exclude_id=row.id))
        notes += result.review_notes
        row.findings = [FindingRow(
            line_no=f.line_no, error_type=f.error_type.value, rule_id=f.rule_id,
            charge_type=f.charge_type.value if f.charge_type else None, expected=f.expected, billed=f.billed,
            difference=f.difference, currency=f.currency, confidence=f.confidence, message=f.message,
            contract_clause=f.evidence.contract_clause, invoice_text=f.evidence.invoice_text) for f in result.findings]
        row.status = "needs_review" if result.needs_review else "audited"
        log_event(s, "invoice", row.id, "audited", "rule_engine", contract=contract.contract_id,
                  findings=len(result.findings), overcharge=str(result.total_overcharge),
                  review_notes=len(result.review_notes))
    row.review_notes = notes
    row.latency_s = time.perf_counter() - t0
    return row, True


def set_finding_status(s: Session, finding_id: int, status: str, actor: str) -> FindingRow:
    if status not in ("open", "accepted", "dismissed"):
        raise WorkflowError("status must be open, accepted or dismissed")
    f = s.get(FindingRow, finding_id)
    if not f:
        raise WorkflowError("finding not found")
    old, f.status = f.status, status
    log_event(s, "finding", f.id, "finding_status_changed", actor, old=old, new=status, invoice_id=f.invoice_id)
    return f


def mark_reviewed(s: Session, invoice_id: int, actor: str) -> InvoiceRow:
    inv = s.get(InvoiceRow, invoice_id)
    if not inv or inv.data is None:
        raise WorkflowError("invoice not found or not extracted")
    inv.status = "audited"
    log_event(s, "invoice", inv.id, "review_completed", actor)
    return inv


# ------------------------------------------------------------------ disputes
def _ctx(inv: InvoiceRow) -> DraftContext:
    fs = [f for f in inv.findings if f.status != "dismissed"]
    return DraftContext(
        carrier=inv.carrier or "", invoice_number=inv.invoice_number or "", bl_number=inv.bl_number or "",
        invoice_date=str(inv.invoice_date), contract_id=inv.contract_id or "",
        findings=[DraftFinding(f.error_type, f.line_no, f.expected, f.billed, Decimal(f.difference), f.currency,
                               f.message, f.contract_clause, f.invoice_text) for f in fs])


def draft_dispute(s: Session, invoice_id: int, actor: str = "system", use_llm: bool = True) -> DisputeRow:
    inv = s.get(InvoiceRow, invoice_id)
    if not inv:
        raise WorkflowError("invoice not found")
    if inv.dispute:  # idempotent: one dispute per invoice
        if inv.dispute.status in ("draft", "rejected"):
            pass  # fall through and redraft in place
        else:
            return inv.dispute
    ctx = _ctx(inv)
    if not ctx.findings:
        raise WorkflowError("no open findings to dispute")
    low = [f for f in inv.findings if f.status == "open" and f.confidence < 0.8]
    if low:
        raise WorkflowError(f"{len(low)} low-confidence finding(s) must be accepted or dismissed first")
    subj, body, by, meta = draft(ctx, llm_client_or_none() if use_llm else None)
    d = inv.dispute or DisputeRow(invoice_id=inv.id)
    d.to_address = f"billing@{(inv.carrier or 'carrier').lower().replace(' ', '')}.example"
    d.subject, d.body, d.drafted_by, d.status = subj, body, by, "draft"
    d.amount, d.currency, d.reviewer, d.review_comment = ctx.total, ctx.currency, None, None
    if d.id is None:
        s.add(d)
    s.flush()
    log_event(s, "dispute", d.id, "drafted", actor, invoice_id=inv.id, drafted_by=by, amount=str(ctx.total), **meta)
    return d


def _dispute(s: Session, dispute_id: int) -> DisputeRow:
    d = s.get(DisputeRow, dispute_id)
    if not d:
        raise WorkflowError("dispute not found")
    return d


def edit_dispute(s: Session, dispute_id: int, subject: str, body: str, actor: str) -> DisputeRow:
    d = _dispute(s, dispute_id)
    if d.status not in ("draft", "rejected"):
        raise WorkflowError(f"cannot edit a dispute in status '{d.status}'")
    d.subject, d.body, d.status = subject, body, "draft"
    log_event(s, "dispute", d.id, "edited", actor, chars=len(body))
    return d


def approve_dispute(s: Session, dispute_id: int, reviewer: str, comment: str | None = None) -> DisputeRow:
    if not reviewer.strip():
        raise WorkflowError("reviewer name required")
    d = _dispute(s, dispute_id)
    if d.status != "draft":
        raise WorkflowError(f"only drafts can be approved (status '{d.status}')")
    d.status, d.reviewer, d.review_comment = "approved", reviewer, comment
    log_event(s, "dispute", d.id, "approved", reviewer, comment=comment)
    return d


def reject_dispute(s: Session, dispute_id: int, reviewer: str, comment: str | None = None) -> DisputeRow:
    d = _dispute(s, dispute_id)
    if d.status not in ("draft", "approved"):
        raise WorkflowError(f"cannot reject a dispute in status '{d.status}'")
    d.status, d.reviewer, d.review_comment = "rejected", reviewer, comment
    log_event(s, "dispute", d.id, "rejected", reviewer, comment=comment)
    return d


def send_dispute(s: Session, dispute_id: int, actor: str) -> DisputeRow:
    """Mock send: writes an .eml to the outbox. Refuses anything not approved by a human."""
    d = _dispute(s, dispute_id)
    if d.status == "sent":
        return d  # idempotent
    if d.status != "approved" or not d.reviewer:
        raise WorkflowError("dispute must be approved by a reviewer before sending")
    settings = get_settings()
    settings.outbox_dir.mkdir(parents=True, exist_ok=True)
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = settings.dispute_from, d.to_address, d.subject
    msg["X-Approved-By"] = d.reviewer
    msg.set_content(d.body)
    path = settings.outbox_dir / f"dispute_{d.id}_invoice_{d.invoice_id}.eml"
    path.write_bytes(bytes(msg))
    d.status, d.sent_at, d.outbox_path = "sent", datetime.now(timezone.utc), str(path)
    log_event(s, "dispute", d.id, "sent_mock", actor, to=d.to_address, path=str(path), approved_by=d.reviewer)
    return d
