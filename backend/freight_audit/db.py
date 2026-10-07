"""Persistence (SQLite locally, PostgreSQL via DATABASE_URL).

The audit log is append-only: ORM updates/deletes of AuditEvent rows are refused,
and each event stores the SHA-256 of its predecessor so tampering is detectable
(GET /api/audit/verify).
"""
from __future__ import annotations

import hashlib
import json
import warnings
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON, Date, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, create_engine, event,
    exc as sa_exc, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

from .config import get_settings

warnings.filterwarnings("ignore", category=sa_exc.SAWarning, message=".*Decimal objects natively.*")
Money = Numeric(16, 4)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ContractRow(Base):
    __tablename__ = "contracts"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    carrier: Mapped[str] = mapped_column(String(200), index=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3))
    data: Mapped[dict] = mapped_column(JSON)  # full Contract document (tax/fx terms)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rates: Mapped[list[ContractRateRow]] = relationship(cascade="all, delete-orphan")
    allowed: Mapped[list[AllowedChargeRow]] = relationship(cascade="all, delete-orphan")


class ContractRateRow(Base):
    __tablename__ = "contract_rates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id"), index=True)
    origin: Mapped[str] = mapped_column(String(5))
    destination: Mapped[str] = mapped_column(String(5))
    container_type: Mapped[str] = mapped_column(String(8))
    charge_type: Mapped[str] = mapped_column(String(32))
    rate: Mapped[Decimal] = mapped_column(Money)
    unit: Mapped[str] = mapped_column(String(32))
    free_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date] = mapped_column(Date)


class AllowedChargeRow(Base):
    __tablename__ = "allowed_charges"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[str] = mapped_column(ForeignKey("contracts.id"), index=True)
    charge_type: Mapped[str] = mapped_column(String(32))


class InvoiceRow(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True)  # idempotency key
    filename: Mapped[str] = mapped_column(String(300))
    source_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    carrier: Mapped[str | None] = mapped_column(String(200), index=True, nullable=True)
    invoice_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    invoice_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bl_number: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    contract_id: Mapped[str | None] = mapped_column(ForeignKey("contracts.id"), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    total: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    status: Mapped[str] = mapped_column(String(20))  # audited | needs_review | failed
    extraction_method: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # normalized Invoice
    review_notes: Mapped[list] = mapped_column(JSON, default=list)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    latency_s: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lines: Mapped[list[InvoiceLineRow]] = relationship(cascade="all, delete-orphan", order_by="InvoiceLineRow.line_no")
    findings: Mapped[list[FindingRow]] = relationship(cascade="all, delete-orphan", order_by="FindingRow.id")
    dispute: Mapped[DisputeRow | None] = relationship(back_populates="invoice", uselist=False)


class InvoiceLineRow(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(300))
    charge_type: Mapped[str] = mapped_column(String(32))
    mapping_confidence: Mapped[float] = mapped_column(Float)
    quantity: Mapped[Decimal] = mapped_column(Money)
    unit_rate: Mapped[Decimal] = mapped_column(Money)
    amount: Mapped[Decimal] = mapped_column(Money)


class FindingRow(Base):
    __tablename__ = "findings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    line_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[str] = mapped_column(String(64))
    charge_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    billed: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    difference: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    confidence: Mapped[float] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    contract_clause: Mapped[str] = mapped_column(Text)
    invoice_text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | accepted | dismissed


class DisputeRow(Base):
    __tablename__ = "disputes"
    __table_args__ = (UniqueConstraint("invoice_id"),)  # one dispute per invoice (idempotent drafting)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"))
    to_address: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | approved | rejected | sent
    drafted_by: Mapped[str] = mapped_column(String(64))
    reviewer: Mapped[str | None] = mapped_column(String(100), nullable=True)
    review_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    outbox_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice: Mapped[InvoiceRow] = relationship(back_populates="dispute")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))


def _event_hash(prev: str, ts: datetime, entity_type: str, entity_id: str, action: str, actor: str, details: dict) -> str:
    if ts.tzinfo is not None:  # SQLite hands back naive UTC; Postgres hands back aware datetimes
        ts = ts.astimezone(timezone.utc).replace(tzinfo=None)
    payload = json.dumps([prev, ts.isoformat(timespec="microseconds"), entity_type, entity_id,
                          action, actor, details], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()


def log_event(s: Session, entity_type: str, entity_id, action: str, actor: str = "system", **details) -> AuditEvent:
    prev = s.scalar(select(AuditEvent.hash).order_by(AuditEvent.id.desc()).limit(1)) or "0" * 64
    ts = utcnow()
    details = json.loads(json.dumps(details, default=str))
    ev = AuditEvent(ts=ts, entity_type=entity_type, entity_id=str(entity_id), action=action, actor=actor,
                    details=details, prev_hash=prev,
                    hash=_event_hash(prev, ts, entity_type, str(entity_id), action, actor, details))
    s.add(ev)
    s.flush()
    return ev


def verify_chain(s: Session) -> dict:
    prev = "0" * 64
    n = 0
    for ev in s.scalars(select(AuditEvent).order_by(AuditEvent.id)):
        expect = _event_hash(prev, ev.ts, ev.entity_type, ev.entity_id, ev.action, ev.actor, ev.details)
        if ev.prev_hash != prev or ev.hash != expect:
            return dict(ok=False, events=n, broken_at=ev.id)
        prev, n = ev.hash, n + 1
    return dict(ok=True, events=n, broken_at=None)


@event.listens_for(Session, "before_flush")
def _audit_log_is_append_only(session: Session, flush_context, instances) -> None:
    for obj in list(session.dirty) + list(session.deleted):
        if isinstance(obj, AuditEvent):
            raise PermissionError("audit_events is append-only")


_engines: dict[str, sessionmaker] = {}


def session_factory(url: str | None = None) -> sessionmaker:
    url = url or get_settings().database_url
    if url not in _engines:
        if url.startswith("sqlite:///"):
            from pathlib import Path

            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        Base.metadata.create_all(engine)
        _engines[url] = sessionmaker(engine, expire_on_commit=False)
    return _engines[url]
