"""End-to-end workflow through the HTTP API (offline: heuristic extractor, template drafts)."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from freight_audit import api
from freight_audit.db import AuditEvent, session_factory
from synth.templates import render_invoice


@pytest.fixture
def client(contracts, monkeypatch):
    monkeypatch.setenv("AUTO_SEED", "0")
    c = TestClient(api.app)
    demo = c.get("/api/auth/config").json()["demo"]
    token = c.post("/api/auth/login", json=demo).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    for k in contracts:
        assert c.post("/api/contracts", content=k.model_dump_json(),
                      headers={"content-type": "application/json"}).status_code == 200
    return c


def upload(c, pdf, name="inv.pdf"):
    r = c.post("/api/invoices", files={"file": (name, pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    return r.json()


def make_pdf(factory, errors=1, tid="T1"):
    while True:
        g = factory.make(error_count=errors, template=tid)
        if errors == 0 or any(l["type"] != "duplicate_invoice" for l in g.labels):
            return g, render_invoice(g.invoice, g.display, tid)


def test_full_review_workflow(client, factory):
    g, pdf = make_pdf(factory, errors=2)
    out = upload(client, pdf)
    inv = out["invoice"]
    assert out["created"] and inv["status"] == "audited"
    assert sorted((f["error_type"], f["line_no"]) for f in inv["finding_list"]) == \
           sorted((l["type"], l["line_no"]) for l in g.labels)
    assert all(f["contract_clause"] and f["invoice_text"] for f in inv["finding_list"])

    d = client.post(f"/api/invoices/{inv['id']}/dispute", json={"actor": "ana"}).json()
    assert d["status"] == "draft" and d["drafted_by"] == "template"

    # Nothing is sent without human approval.
    r = client.post(f"/api/disputes/{d['id']}/send", json={"actor": "ana"})
    assert r.status_code == 409

    edited = client.put(f"/api/disputes/{d['id']}", json={"actor": "ana", "subject": d["subject"],
                                                           "body": d["body"] + "\nRef: PO-77"}).json()
    assert "PO-77" in edited["body"]
    assert client.post(f"/api/disputes/{d['id']}/approve", json={"reviewer": "ana"}).json()["status"] == "approved"
    sent = client.post(f"/api/disputes/{d['id']}/send", json={"actor": "ana"}).json()
    assert sent["status"] == "sent" and sent["outbox_path"].endswith(".eml")
    with open(sent["outbox_path"], encoding="utf-8") as fh:
        eml = fh.read()
    # The approver is the signed-in user, not whatever name the client sends.
    assert "X-Approved-By: Alex Morgan" in eml and "PO-77" in eml

    actions = [e["action"] for e in client.get("/api/audit").json()]
    for a in ("uploaded", "extracted", "audited", "drafted", "edited", "approved", "sent_mock"):
        assert a in actions
    assert client.get("/api/audit/verify").json()["ok"]


def test_reupload_is_idempotent_but_rebill_is_flagged(client, factory):
    g, pdf = make_pdf(factory, errors=0)
    first = upload(client, pdf)
    again = upload(client, pdf)
    assert again["created"] is False and again["invoice"]["id"] == first["invoice"]["id"]
    assert len(client.get("/api/invoices").json()) == 1

    dup = factory.duplicate_of(g, "T2")  # same shipment, new invoice number and layout
    out = upload(client, render_invoice(dup.invoice, dup.display, "T2"), "rebill.pdf")
    assert [f["error_type"] for f in out["invoice"]["finding_list"]] == ["duplicate_invoice"]

    d1 = client.post(f"/api/invoices/{out['invoice']['id']}/dispute", json={}).json()
    d2 = client.post(f"/api/invoices/{out['invoice']['id']}/dispute", json={}).json()
    assert d1["id"] == d2["id"]  # one dispute per invoice


def test_dismissed_findings_leave_dispute(client, factory):
    _, pdf = make_pdf(factory, errors=2)
    inv = upload(client, pdf)["invoice"]
    first = inv["finding_list"][0]
    client.patch(f"/api/findings/{first['id']}", json={"status": "dismissed", "actor": "ana"})
    d = client.post(f"/api/invoices/{inv['id']}/dispute", json={"actor": "ana"}).json()
    remaining = sum(f["difference"] for f in inv["finding_list"][1:])
    assert d["amount"] == pytest.approx(remaining, abs=0.01)


def test_unreadable_pdf_goes_to_review(client, factory):
    g = factory.make(error_count=1, template="T5")
    inv = upload(client, render_invoice(g.invoice, g.display, "T5"))["invoice"]
    assert inv["status"] == "needs_review" and inv["finding_list"] == []
    assert "Extraction failed" in inv["review_notes"][0]


def test_audit_log_is_append_only(client, factory):
    upload(client, make_pdf(factory)[1])
    s = session_factory()()
    ev = s.scalars(select(AuditEvent)).first()
    ev.action = "tampered"
    with pytest.raises(PermissionError):
        s.commit()
    s.rollback()
    s.close()


def test_agent_offline_router(client, factory):
    inv = upload(client, make_pdf(factory, errors=1)[1])["invoice"]
    r = client.post("/api/agent/chat", json={"message": "what is wrong with this invoice?",
                                             "invoice_id": inv["id"]}).json()
    assert r["mode"] == "offline" and inv["invoice_number"] in r["answer"]
    assert r["tool_calls"][0]["tool"] == "check_invoice"


def test_api_requires_login(contracts):
    c = TestClient(api.app)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/invoices").status_code == 401
    assert c.get("/api/invoices", headers={"Authorization": "Bearer forged.token"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "reviewer@freightaudit.demo", "password": "wrong"}).status_code == 401


def test_tampered_or_expired_token_rejected(monkeypatch):
    from freight_audit import auth

    token, _ = auth.login(**auth.demo_credentials())
    payload, sig = token.rsplit(".", 1)
    assert auth.verify(token).name == "Alex Morgan"
    assert auth.verify(payload[:-2] + "xx." + sig) is None
    monkeypatch.setattr(auth.time, "time", lambda: 10**12)
    assert auth.verify(token) is None
