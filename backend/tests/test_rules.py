from datetime import date
from decimal import Decimal as D

import pytest

from freight_audit.models import ChargeType as CT, ErrorType as ET, InvoiceLine
from freight_audit.rules import PriorInvoice, audit_invoice


def key(pair):
    return (str(pair[0]), pair[1] or 0)


def types(res):
    return sorted(((f.error_type, f.line_no) for f in res.findings), key=key)


def test_clean_invoice_has_no_findings(contract, clean_invoice):
    res = audit_invoice(clean_invoice, contract)
    assert res.findings == [] and res.review_notes == []


def test_wrong_rate(contract, clean_invoice):
    l = clean_invoice.lines[1]
    l.unit_rate, l.amount = D("450"), D("900")
    clean_invoice.subtotal = clean_invoice.total = D("5360")
    res = audit_invoice(clean_invoice, contract)
    assert types(res) == [(ET.WRONG_RATE, 2)]
    f = res.findings[0]
    assert (f.expected, f.billed, f.difference) == (D("400.00"), D("450.00"), D("100.00"))
    assert "400.00" in f.evidence.contract_clause and "Line 2" in f.evidence.invoice_text


def test_expired_rate_is_distinguished_from_wrong_rate(contract, clean_invoice):
    l = clean_invoice.lines[0]
    l.unit_rate, l.amount = D("2200"), D("4400")  # H1 rate on an August shipment
    clean_invoice.subtotal = clean_invoice.total = D("5660")
    res = audit_invoice(clean_invoice, contract)
    assert types(res) == [(ET.EXPIRED_RATE, 1)]
    assert res.findings[0].difference == D("400.00")


def test_undercharge_is_not_disputed(contract, clean_invoice):
    l = clean_invoice.lines[1]
    l.unit_rate, l.amount = D("350"), D("700")
    clean_invoice.subtotal = clean_invoice.total = D("5160")
    assert audit_invoice(clean_invoice, contract).findings == []


def test_duplicate_line(contract, clean_invoice):
    dup = clean_invoice.lines[2].model_copy(update={"line_no": 5})
    clean_invoice.lines.append(dup)
    clean_invoice.subtotal = clean_invoice.total = D("5320")
    assert types(audit_invoice(clean_invoice, contract)) == [(ET.DUPLICATE_LINE, 5)]


def test_unauthorized_charge(contract, clean_invoice):
    clean_invoice.lines.append(InvoiceLine(line_no=5, description="Peak Season Surcharge", charge_type=CT.PEAK_SEASON,
                                           quantity=D(2), unit_rate=D("150"), amount=D("300")))
    clean_invoice.subtotal = clean_invoice.total = D("5560")
    res = audit_invoice(clean_invoice, contract)
    assert types(res) == [(ET.UNAUTHORIZED_CHARGE, 5)] and res.findings[0].difference == D("300.00")


def test_line_math_and_total_math(contract, clean_invoice):
    clean_invoice.lines[2].amount = D("90")  # 1 x 60 billed as 90
    clean_invoice.subtotal = D("5290")
    clean_invoice.total = D("5340")  # +50 over subtotal + tax
    res = audit_invoice(clean_invoice, contract)
    assert types(res) == [(ET.CALCULATION_ERROR, None), (ET.CALCULATION_ERROR, 3)]
    assert sorted(f.difference for f in res.findings) == [D("30.00"), D("50.00")]


def test_detention_free_days_not_applied(contract, clean_invoice):
    l = clean_invoice.lines[3]
    l.quantity, l.amount = D(28), D("1400")  # 14 days x 2 containers, ignoring 10 free days
    clean_invoice.subtotal = clean_invoice.total = D("6260")
    res = audit_invoice(clean_invoice, contract)
    assert types(res) == [(ET.DETENTION_DEMURRAGE, 4)]
    f = res.findings[0]
    assert (f.expected, f.billed, f.difference) == (D("400.00"), D("1400.00"), D("1000.00"))
    assert "10 free days" in f.message


def test_detention_without_dates_goes_to_review(contract, clean_invoice):
    clean_invoice.equipment_out = None
    res = audit_invoice(clean_invoice, contract)
    assert res.findings == [] and res.needs_review


def test_tax_overcharge(contract, clean_invoice):
    clean_invoice.tax_rate, clean_invoice.tax_amount = D("0.18"), D("946.80")
    clean_invoice.total = D("6206.80")
    res = audit_invoice(clean_invoice, contract)
    assert types(res) == [(ET.CURRENCY_TAX, None)] and res.findings[0].difference == D("946.80")


def test_fx_rate_inflated(contract, clean_invoice):
    fx = D("88.40")  # agreed 85.00
    inv = clean_invoice
    inv.currency, inv.exchange_rate = "INR", fx
    for l in inv.lines:
        l.unit_rate = (l.unit_rate * fx).quantize(D("0.01"))
        l.amount = l.quantity * l.unit_rate
    inv.subtotal = sum(l.amount for l in inv.lines)
    inv.tax_rate, inv.tax_amount = D("0.05"), (inv.subtotal * D("0.05")).quantize(D("0.01"))
    inv.total = inv.subtotal + inv.tax_amount
    res = audit_invoice(inv, contract)
    assert types(res) == [(ET.CURRENCY_TAX, None)]
    # Line rates are judged at the invoice's own FX, so only the FX finding fires.
    assert res.findings[0].rule_id == "fx_rate"


@pytest.mark.parametrize("same_number", [True, False])
def test_duplicate_invoice(contract, clean_invoice, same_number):
    prior = PriorInvoice(1, "TL-001" if same_number else "TL-000", "Test Line", "TL123", D("5260"), "USD")
    res = audit_invoice(clean_invoice, contract, [prior])
    assert types(res) == [(ET.DUPLICATE_INVOICE, None)]


def test_other_carrier_same_number_is_not_duplicate(contract, clean_invoice):
    prior = PriorInvoice(1, "TL-001", "Other Line", "XX999", D("10"), "USD")
    assert audit_invoice(clean_invoice, contract, [prior]).findings == []


def test_unknown_charge_routes_to_review(contract, clean_invoice):
    clean_invoice.lines[2].charge_type = CT.UNKNOWN
    res = audit_invoice(clean_invoice, contract)
    assert res.findings == [] and res.needs_review


def test_ship_date_outside_contract_flags_review(contract, clean_invoice):
    clean_invoice.ship_date = date(2027, 2, 1)
    res = audit_invoice(clean_invoice, contract)
    assert res.needs_review and not any(f.error_type == ET.WRONG_RATE for f in res.findings)


def test_engine_agrees_with_generator_labels(factory, contracts):
    """Property test: on ground-truth invoices, findings == injected labels (type, line, overcharge)."""
    by_id = {c.contract_id: c for c in contracts}
    history = []
    for i in range(300):
        g = factory.make(error_count=i % 4, template="T1")
        res = audit_invoice(g.invoice, by_id[g.invoice.contract_ref], history)
        got = sorted(((f.error_type.value, f.line_no) for f in res.findings), key=key)
        want = sorted(((l["type"], l["line_no"]) for l in g.labels), key=key)
        assert got == want, (g.labels, [f.message for f in res.findings])
        for lab in g.labels:
            f = next(f for f in res.findings if (f.error_type.value, f.line_no) == (lab["type"], lab["line_no"]))
            assert abs(float(f.difference) - lab["overcharge"]) <= max(0.05, 0.002 * lab["overcharge"])
        history.append(PriorInvoice(i, g.invoice.invoice_number, g.invoice.carrier, g.invoice.bl_number,
                                    g.invoice.total, g.invoice.currency))
