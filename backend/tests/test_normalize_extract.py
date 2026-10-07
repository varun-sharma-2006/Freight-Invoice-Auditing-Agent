from datetime import date
from decimal import Decimal as D

import pytest

from freight_audit.extraction import ExtractionError, extract
from freight_audit.extraction.base import assemble
from freight_audit.models import ChargeType as CT
from freight_audit.normalize import map_charge, normalize_container_type, normalize_port, parse_date, parse_decimal
from synth.generator import DESCRIPTIONS
from synth.templates import fmt_num, rasterize, render_invoice


@pytest.mark.parametrize("ct,desc", [(ct, d) for ct, ds in DESCRIPTIONS.items() for d in ds])
def test_dev_vocabulary_maps(ct, desc):
    assert map_charge(desc)[0] == ct


@pytest.mark.parametrize("desc,ct", [
    ("Emergency Bunker Surcharge", CT.EMERGENCY_BUNKER), ("bunker adj.", CT.FUEL_SURCHARGE),
    ("Origin THC", CT.THC_ORIGIN), ("Import THC", CT.THC_DEST), ("Terminal Demurrage", CT.DEMURRAGE),
    ("Something odd", CT.UNKNOWN)])
def test_charge_mapping_edge_cases(desc, ct):
    assert map_charge(desc)[0] == ct


def test_charge_code_beats_description():
    assert map_charge("Misc", "BAF") == (CT.FUEL_SURCHARGE, 1.0)


def test_scalars():
    assert normalize_container_type("40' High Cube") == "40HC"
    assert normalize_container_type("20' Dry Standard") == "20GP"
    assert normalize_port("NHAVA SHEVA, IN (INNSA)") == "INNSA"
    assert normalize_port("Rotterdam, NL") == "NLRTM"
    assert parse_date("04/03/2026") == date(2026, 3, 4)  # day-first
    assert parse_date("04-Mar-2026") == parse_date("Mar 04, 2026") == date(2026, 3, 4)
    assert parse_decimal("INR 3,16,635.02") == D("316635.02")
    assert fmt_num(D("316635.02"), indian=True) == "3,16,635.02"


def test_assemble_rejects_missing_required_fields():
    with pytest.raises(ExtractionError):
        assemble({"invoice_number": "X", "lines": []})


@pytest.mark.parametrize("tid", ["T1", "T2", "T3", "T4"])
def test_heuristic_roundtrip(factory, tid):
    for n in range(6):
        g = factory.make(error_count=n % 3, template=tid)
        got = extract(render_invoice(g.invoice, g.display, tid), mode="heuristic").invoice
        exp = g.invoice
        for f in ("invoice_number", "carrier", "invoice_date", "bl_number", "origin", "destination", "container_type",
                  "container_count", "ship_date", "currency", "exchange_rate", "equipment_out", "equipment_in",
                  "discharge_date", "pickup_date", "subtotal", "tax_amount", "total"):
            assert getattr(got, f) == getattr(exp, f), f
        assert [(l.charge_type, l.quantity, l.unit_rate, l.amount) for l in got.lines] == \
               [(l.charge_type, l.quantity, l.unit_rate, l.amount) for l in exp.lines]


def test_heldout_layout_fails_safe_offline(factory):
    """The offline parser cannot read the unseen T5 layout; it must refuse, not guess."""
    g = factory.make(error_count=1, template="T5")
    with pytest.raises(ExtractionError):
        extract(render_invoice(g.invoice, g.display, "T5"), mode="heuristic")


def test_scanned_pdf_needs_vision(factory):
    g = factory.make(error_count=0, template="T1")
    with pytest.raises(ExtractionError, match="Scanned"):
        extract(rasterize(render_invoice(g.invoice, g.display, "T1")))
