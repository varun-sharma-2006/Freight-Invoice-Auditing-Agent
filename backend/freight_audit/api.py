"""HTTP API.  Run:  uvicorn freight_audit.api:app --reload  (from backend/)"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import agent, services
from .config import ROOT, get_settings
from .db import AuditEvent, ContractRow, DisputeRow, InvoiceRow, session_factory, verify_chain
from .models import Contract

app = FastAPI(title="Freight Invoice Auditing Agent", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
                   allow_methods=["*"], allow_headers=["*"])
SAMPLES = ROOT / "data" / "synthetic"
EVAL_RESULTS = ROOT / "backend" / "evals" / "results"
MAX_UPLOAD_BYTES = 10_000_000  # public demo: refuse oversized uploads


def db() -> Iterator[Session]:
    s = session_factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def wf(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except services.WorkflowError as e:
        raise HTTPException(409, str(e)) from e


# ------------------------------------------------------------------ views
def dispute_view(d: DisputeRow | None) -> dict | None:
    if d is None:
        return None
    return dict(id=d.id, invoice_id=d.invoice_id, to_address=d.to_address, subject=d.subject, body=d.body,
                amount=float(d.amount), currency=d.currency, status=d.status, drafted_by=d.drafted_by,
                reviewer=d.reviewer, review_comment=d.review_comment, outbox_path=d.outbox_path,
                sent_at=d.sent_at, updated_at=d.updated_at)


def invoice_summary(r: InvoiceRow) -> dict:
    open_f = [f for f in r.findings if f.status != "dismissed"]
    return dict(id=r.id, filename=r.filename, carrier=r.carrier, invoice_number=r.invoice_number,
                invoice_date=r.invoice_date, bl_number=r.bl_number, contract_id=r.contract_id, currency=r.currency,
                total=float(r.total) if r.total is not None else None, status=r.status,
                findings=len(open_f), overcharge=float(sum(f.difference for f in open_f)),
                dispute_status=r.dispute.status if r.dispute else None, created_at=r.created_at)


def invoice_detail(r: InvoiceRow) -> dict:
    return dict(
        **invoice_summary(r), extraction_method=r.extraction_method, cost_usd=r.cost_usd, latency_s=r.latency_s,
        review_notes=r.review_notes, invoice=r.data,
        lines=[dict(line_no=l.line_no, description=l.description, charge_type=l.charge_type,
                    mapping_confidence=l.mapping_confidence, quantity=float(l.quantity), unit_rate=float(l.unit_rate),
                    amount=float(l.amount)) for l in r.lines],
        finding_list=[dict(id=f.id, line_no=f.line_no, error_type=f.error_type, rule_id=f.rule_id,
                           charge_type=f.charge_type, expected=None if f.expected is None else float(f.expected),
                           billed=None if f.billed is None else float(f.billed), difference=float(f.difference),
                           currency=f.currency, confidence=f.confidence, message=f.message,
                           contract_clause=f.contract_clause, invoice_text=f.invoice_text, status=f.status)
                      for f in r.findings],
        dispute=dispute_view(r.dispute))


# ------------------------------------------------------------------ meta
@app.get("/api/health")
def health():
    s = get_settings()
    return dict(ok=True, llm_configured=bool(s.api_key), model=s.gemini_model, extractor=s.extractor)


# ------------------------------------------------------------------ contracts
@app.post("/api/contracts")
def create_contract(contract: Contract, s: Session = Depends(db)):
    services.upsert_contract(s, contract, actor="api")
    return dict(contract_id=contract.contract_id, rates=len(contract.rates))


@app.post("/api/contracts/upload")
async def upload_contract(file: UploadFile = File(...), s: Session = Depends(db)):
    try:
        contract = Contract.model_validate_json(await file.read())
    except ValueError as e:
        raise HTTPException(422, f"Invalid contract JSON: {e}") from e
    services.upsert_contract(s, contract, actor="api")
    return dict(contract_id=contract.contract_id, rates=len(contract.rates))


@app.get("/api/contracts")
def list_contracts(s: Session = Depends(db)):
    return [dict(id=c.id, carrier=c.carrier, valid_from=c.valid_from, valid_to=c.valid_to, currency=c.currency,
                 rates=len(c.rates)) for c in s.scalars(select(ContractRow).order_by(ContractRow.id))]


@app.get("/api/contracts/{contract_id}")
def get_contract(contract_id: str, s: Session = Depends(db)):
    c = services.get_contract(s, contract_id)
    if not c:
        raise HTTPException(404, "contract not found")
    return c


# ------------------------------------------------------------------ demo helpers
@app.post("/api/demo/seed")
def seed(s: Session = Depends(db)):
    files = sorted((SAMPLES / "contracts").glob("*.json"))
    if not files:
        raise HTTPException(404, "No synthetic contracts. Run: python -m synth.generator")
    for p in files:
        services.upsert_contract(s, Contract.model_validate_json(p.read_text(encoding="utf-8")), actor="demo_seed")
    return dict(loaded=[p.stem for p in files])


@app.get("/api/demo/samples")
def samples(split: str = "test", limit: int = 40):
    path = SAMPLES / split / "labels.jsonl"
    if not path.exists():
        return []
    rows = [json.loads(l) for l in path.open(encoding="utf-8")][:limit]
    return [dict(file=r["file"], template=r["template"], injected=[e["type"] for e in r["errors"]]) for r in rows]


@app.post("/api/demo/samples/{split}/{name}")
def process_sample(split: str, name: str, s: Session = Depends(db)):
    path = (SAMPLES / split / name).resolve()
    if path.parent != (SAMPLES / split).resolve() or not path.is_file():
        raise HTTPException(404, "sample not found")
    row, created = services.process_invoice(s, path.read_bytes(), name, actor="demo")
    return dict(created=created, invoice=invoice_detail(row))


# ------------------------------------------------------------------ invoices
@app.post("/api/invoices")
async def upload_invoice(file: UploadFile = File(...), contract_id: str | None = Form(None),
                         extractor: str | None = Form(None), s: Session = Depends(db)):
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"PDF larger than {MAX_UPLOAD_BYTES // 1_000_000} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Please upload a PDF")
    row, created = services.process_invoice(s, data, file.filename or "invoice.pdf", contract_id or None,
                                            extractor or None, actor="api")
    return dict(created=created, invoice=invoice_detail(row))


@app.get("/api/invoices")
def list_invoices(s: Session = Depends(db)):
    return [invoice_summary(r) for r in s.scalars(select(InvoiceRow).order_by(InvoiceRow.id.desc()))]


def _invoice(s: Session, invoice_id: int) -> InvoiceRow:
    r = s.get(InvoiceRow, invoice_id)
    if not r:
        raise HTTPException(404, "invoice not found")
    return r


@app.get("/api/invoices/{invoice_id}")
def get_invoice(invoice_id: int, s: Session = Depends(db)):
    return invoice_detail(_invoice(s, invoice_id))


@app.get("/api/invoices/{invoice_id}/pdf")
def invoice_pdf(invoice_id: int, s: Session = Depends(db)):
    r = _invoice(s, invoice_id)
    if not r.source_path or not Path(r.source_path).exists():
        raise HTTPException(404, "file not stored")
    return FileResponse(r.source_path, media_type="application/pdf", filename=r.filename,
                        content_disposition_type="inline")


class Actor(BaseModel):
    actor: str = "reviewer"


class FindingStatus(Actor):
    status: str


@app.patch("/api/findings/{finding_id}")
def update_finding(finding_id: int, body: FindingStatus, s: Session = Depends(db)):
    f = wf(services.set_finding_status, s, finding_id, body.status, body.actor)
    return invoice_detail(_invoice(s, f.invoice_id))


@app.post("/api/invoices/{invoice_id}/reviewed")
def reviewed(invoice_id: int, body: Actor, s: Session = Depends(db)):
    wf(services.mark_reviewed, s, invoice_id, body.actor)
    return invoice_detail(_invoice(s, invoice_id))


# ------------------------------------------------------------------ disputes
@app.post("/api/invoices/{invoice_id}/dispute")
def create_dispute(invoice_id: int, body: Actor, s: Session = Depends(db)):
    d = wf(services.draft_dispute, s, invoice_id, body.actor)
    return dispute_view(d)


class DisputeEdit(Actor):
    subject: str
    body: str


class Review(BaseModel):
    reviewer: str
    comment: str | None = None


@app.put("/api/disputes/{dispute_id}")
def edit_dispute(dispute_id: int, body: DisputeEdit, s: Session = Depends(db)):
    return dispute_view(wf(services.edit_dispute, s, dispute_id, body.subject, body.body, body.actor))


@app.post("/api/disputes/{dispute_id}/approve")
def approve(dispute_id: int, body: Review, s: Session = Depends(db)):
    return dispute_view(wf(services.approve_dispute, s, dispute_id, body.reviewer, body.comment))


@app.post("/api/disputes/{dispute_id}/reject")
def reject(dispute_id: int, body: Review, s: Session = Depends(db)):
    return dispute_view(wf(services.reject_dispute, s, dispute_id, body.reviewer, body.comment))


@app.post("/api/disputes/{dispute_id}/send")
def send(dispute_id: int, body: Actor, s: Session = Depends(db)):
    return dispute_view(wf(services.send_dispute, s, dispute_id, body.actor))


# ------------------------------------------------------------------ audit log & agent
@app.get("/api/audit")
def audit_log(entity_type: str | None = None, entity_id: str | None = None, limit: int = 200,
              s: Session = Depends(db)):
    q = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(limit)
    if entity_type:
        q = q.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        q = q.where(AuditEvent.entity_id == entity_id)
    return [dict(id=e.id, ts=e.ts, entity_type=e.entity_type, entity_id=e.entity_id, action=e.action, actor=e.actor,
                 details=e.details, hash=e.hash[:12]) for e in s.scalars(q)]


@app.get("/api/audit/verify")
def audit_verify(s: Session = Depends(db)):
    return verify_chain(s)


class ChatIn(BaseModel):
    message: str
    invoice_id: int | None = None


@app.post("/api/agent/chat")
def agent_chat(body: ChatIn, s: Session = Depends(db)):
    return agent.chat(s, body.message, body.invoice_id)


@app.get("/api/eval/results")
def eval_results():
    out = []
    for p in sorted(EVAL_RESULTS.glob("*.json")):
        r = json.loads(p.read_text(encoding="utf-8"))
        r.pop("invoices", None)
        out.append(dict(name=p.stem, **r))
    return out
