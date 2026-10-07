"""LLM-facing code tested with fake clients (no network)."""
import json
from decimal import Decimal as D

import pytest

from freight_audit.drafting import DraftContext, DraftFinding, draft, unsupported_figures
from freight_audit.extraction.gemini import GeminiExtractor, LLMInvoice
from freight_audit.llm import GeminiClient, Usage


def ctx():
    return DraftContext(carrier="Test Line", invoice_number="TL-1", invoice_date="2026-08-20", bl_number="BL1",
                        contract_id="SC-1", findings=[DraftFinding(
                            "wrong_rate", 2, D("400.00"), D("450.00"), D("100.00"), "USD",
                            "Billed rate USD 450.00 exceeds contracted USD 400.00.", "rate = USD 400.00",
                            "Line 2: 'BAF' 2 x USD 450.00 = USD 900.00")])


class FakeTextClient:
    model = "fake"

    def __init__(self, body):
        self.body = body

    def text(self, contents, system, usage, temperature=0.2):
        return self.body


def test_template_draft_has_only_supported_figures():
    subj, body, by, _ = draft(ctx())
    assert by == "template" and "100.00" in subj and unsupported_figures(body, ctx()) == []


def test_llm_draft_accepted_when_figures_match():
    _, body, by, _ = draft(ctx(), FakeTextClient("Please credit USD 100.00 (billed 450.00 vs 400.00)."))
    assert by == "llm:fake" and "credit" in body


def test_llm_draft_with_invented_number_falls_back():
    _, body, by, meta = draft(ctx(), FakeTextClient("Please credit USD 1,250.00 immediately."))
    assert by == "template" and "unsupported" in meta["fallback_reason"] and "1,250.00" not in body


class FakeResp:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


class FakeGemini(GeminiClient):
    """Returns queued responses; exercises the real validate-and-retry loop."""

    def __init__(self, responses):
        self.model, self.responses, self.prompts = "fake", list(responses), []

    def _generate(self, **kw):
        self.prompts.append(kw["contents"])
        return FakeResp(self.responses.pop(0))


GOOD = LLMInvoice(
    carrier="Test Line", invoice_number="TL-9", invoice_date="2026-08-20", bl_number="TL999",
    origin="Nhava Sheva (INNSA)", destination="Rotterdam", container_type="40' High Cube", container_count=2,
    ship_date="2026-08-01", currency="USD", subtotal=4000.0, tax_amount=0.0, total=4000.0,
    lines=[dict(description="Ocean Freight", quantity=2, unit_rate=2000.0, amount=4000.0)])


def test_structured_retries_on_invalid_json():
    client = FakeGemini(["not json", json.dumps({"lines": "oops"}), GOOD.model_dump_json()])
    out = client.structured(["x"], LLMInvoice, "sys", Usage())
    assert out.invoice_number == "TL-9" and len(client.prompts) == 3
    assert "failed validation" in client.prompts[-1][-1]


def test_structured_gives_up_after_retries():
    with pytest.raises(ValueError):
        FakeGemini(["bad", "bad", "bad"]).structured(["x"], LLMInvoice, "sys", Usage())


def test_gemini_extractor_normalizes(monkeypatch):
    monkeypatch.setattr("freight_audit.extraction.gemini.pdf_part", lambda b: "PDF")
    res = GeminiExtractor(FakeGemini([GOOD.model_dump_json()])).extract(b"%PDF")
    inv = res.invoice
    assert (inv.origin, inv.destination, inv.container_type) == ("INNSA", "NLRTM", "40HC")
    assert inv.lines[0].charge_type.value == "BASE_FREIGHT"
