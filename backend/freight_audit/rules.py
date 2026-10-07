"""Deterministic rule engine: compares a normalized invoice against its contract.

No LLM is involved here. Every finding carries the contract clause and invoice
line it is based on, and only overcharges are reported (undercharges are not
disputed). Amounts in findings are converted to the contract currency.
"""
from __future__ import annotations

from dataclasses import dataclass

from decimal import ROUND_HALF_UP, Decimal

from .models import (
    AuditResult, ChargeType, Contract, ContractRate, ErrorType, Evidence, Finding, Invoice,
    InvoiceLine, RateUnit,
)

CENT = Decimal("0.01")
MATH_TOL = Decimal("0.05")  # invoice-currency rounding tolerance for arithmetic checks
RATE_TOL = Decimal("0.005")  # relative tolerance on rate comparisons (FX rounding)
REVIEW_THRESHOLD = 0.8
DND = {ChargeType.DETENTION, ChargeType.DEMURRAGE}


@dataclass(frozen=True)
class PriorInvoice:
    """Minimal view of an already-processed invoice, for duplicate detection."""
    invoice_id: int | str
    invoice_number: str
    carrier: str
    bl_number: str
    total: Decimal
    currency: str


def q(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


def _fmt(x: Decimal | None, ccy: str = "") -> str:
    if x is None:
        return "n/a"
    return f"{ccy} {q(x):,.2f}".strip()


def _line_text(line: InvoiceLine, ccy: str) -> str:
    return (f"Line {line.line_no}: '{line.description}' {line.quantity} x {_fmt(line.unit_rate, ccy)}"
            f" = {_fmt(line.amount, ccy)}")


def _rate_clause(c: Contract, r: ContractRate) -> str:
    extra = f", {r.free_days} free days" if r.free_days is not None else ""
    return (f"Contract {c.contract_id} rate table: {r.origin}->{r.destination} {r.container_type} "
            f"{r.charge_type.value} = {_fmt(r.rate, c.currency)} {r.unit.value}{extra}, "
            f"valid {r.valid_from} to {r.valid_to}")


class RuleEngine:
    def __init__(self, contract: Contract):
        self.c = contract

    # ------------------------------------------------------------ helpers
    def _rates_for(self, inv: Invoice, ct: ChargeType) -> list[ContractRate]:
        return [r for r in self.c.rates
                if r.charge_type == ct and r.origin == inv.origin and r.destination == inv.destination
                and r.container_type == inv.container_type]

    def _billing_fx(self, inv: Invoice) -> Decimal | None:
        """Invoice-currency units per contract-currency unit, as stated on the invoice."""
        if inv.currency == self.c.currency:
            return Decimal("1")
        return inv.exchange_rate or self.c.fx_rates.get(inv.currency)

    @staticmethod
    def _conf(inv: Invoice, *fields: str) -> float:
        return min([inv.field_confidence.get(f, 1.0) for f in fields] or [1.0])

    # ------------------------------------------------------------ main
    def audit(self, inv: Invoice, history: list[PriorInvoice] | None = None) -> AuditResult:
        res = AuditResult()
        c = self.c
        for f, conf in inv.field_confidence.items():
            if conf < REVIEW_THRESHOLD:
                res.review_notes.append(f"Low-confidence extraction for '{f}' ({conf:.2f}); verify manually.")

        if inv.contract_ref and inv.contract_ref != c.contract_id:
            res.review_notes.append(f"Invoice references contract {inv.contract_ref}, audited against {c.contract_id}.")
        if not (c.valid_from <= inv.ship_date <= c.valid_to):
            res.review_notes.append(
                f"Ship date {inv.ship_date} is outside contract validity {c.valid_from}..{c.valid_to}.")

        fx = self._billing_fx(inv)
        if fx is None:
            res.review_notes.append(f"No agreed exchange rate for {inv.currency}; cannot convert to {c.currency}.")
            return res

        self._check_duplicates_invoice(inv, history or [], fx, res)
        self._check_fx(inv, fx, res)
        seen: dict[tuple, int] = {}
        for line in inv.lines:
            self._check_line(inv, line, fx, seen, res)
        self._check_totals(inv, fx, res)
        return res

    # ------------------------------------------------------------ invoice level
    def _check_duplicates_invoice(self, inv: Invoice, history: list[PriorInvoice], fx: Decimal,
                                  res: AuditResult) -> None:
        for p in history:
            if p.carrier.lower() != inv.carrier.lower():
                continue
            same_number = p.invoice_number.strip().upper() == inv.invoice_number.strip().upper()
            rebilled = p.bl_number == inv.bl_number and abs(p.total - inv.total) <= MATH_TOL
            if same_number or rebilled:
                why = "same invoice number" if same_number else "same B/L and identical total under a new invoice number"
                res.findings.append(Finding(
                    error_type=ErrorType.DUPLICATE_INVOICE, rule_id="duplicate_invoice",
                    billed=q(inv.total / fx), expected=Decimal("0"), difference=q(inv.total / fx),
                    currency=self.c.currency, confidence=self._conf(inv, "invoice_number", "bl_number", "total"),
                    message=f"Invoice duplicates previously processed invoice {p.invoice_number} ({why}).",
                    evidence=Evidence(
                        contract_clause="Each shipment (B/L) may be invoiced once.",
                        invoice_text=f"Invoice {inv.invoice_number}, B/L {inv.bl_number}, total {_fmt(inv.total, inv.currency)}; "
                                     f"prior invoice {p.invoice_number}, B/L {p.bl_number}, total {_fmt(p.total, p.currency)}")))
                return

    def _check_fx(self, inv: Invoice, fx: Decimal, res: AuditResult) -> None:
        if inv.currency == self.c.currency:
            return
        agreed = self.c.fx_rates.get(inv.currency)
        if agreed is None or fx <= agreed * (1 + self.c.fx_tolerance):
            return
        lines_sum = sum((l.amount for l in inv.lines), Decimal("0"))
        over = q(lines_sum / agreed - lines_sum / fx)
        res.findings.append(Finding(
            error_type=ErrorType.CURRENCY_TAX, rule_id="fx_rate", expected=agreed, billed=fx,
            difference=over, currency=self.c.currency, confidence=self._conf(inv, "exchange_rate"),
            message=f"Exchange rate {fx} {inv.currency}/{self.c.currency} exceeds the agreed {agreed} "
                    f"(tolerance {self.c.fx_tolerance:%}).",
            evidence=Evidence(
                contract_clause=f"Contract {self.c.contract_id}: agreed rate 1 {self.c.currency} = {agreed} {inv.currency}",
                invoice_text=f"Invoice states 1 {self.c.currency} = {fx} {inv.currency}")))

    # ------------------------------------------------------------ line level
    def _check_line(self, inv: Invoice, line: InvoiceLine, fx: Decimal, seen: dict, res: AuditResult) -> None:
        c, ccy = self.c, inv.currency
        conf = min(line.mapping_confidence, self._conf(inv, "lines"))
        ltext = _line_text(line, ccy)

        # 1. arithmetic
        calc = line.quantity * line.unit_rate
        if line.amount - calc > MATH_TOL:
            res.findings.append(Finding(
                error_type=ErrorType.CALCULATION_ERROR, rule_id="line_math", line_no=line.line_no,
                charge_type=line.charge_type, expected=q(calc / fx), billed=q(line.amount / fx),
                difference=q((line.amount - calc) / fx), currency=c.currency, confidence=conf,
                message=f"Line {line.line_no} amount does not equal quantity x rate ({_fmt(calc, ccy)}).",
                evidence=Evidence(contract_clause="Line amount must equal quantity x unit rate.", invoice_text=ltext)))

        if line.charge_type == ChargeType.UNKNOWN:
            res.review_notes.append(f"Line {line.line_no}: could not map '{line.description}' to a charge type.")
            return

        # 2. duplicate line within the invoice
        key = (line.charge_type, line.quantity, line.unit_rate, line.amount)
        if key in seen and line.charge_type not in DND:
            res.findings.append(Finding(
                error_type=ErrorType.DUPLICATE_LINE, rule_id="duplicate_line", line_no=line.line_no,
                charge_type=line.charge_type, expected=Decimal("0"), billed=q(line.amount / fx),
                difference=q(line.amount / fx), currency=c.currency, confidence=conf,
                message=f"Line {line.line_no} repeats line {seen[key]} ({line.charge_type.value}).",
                evidence=Evidence(contract_clause="Each charge applies once per shipment.", invoice_text=ltext)))
            return
        seen[key] = line.line_no

        # 3. charge allowed by contract?
        if line.charge_type not in c.allowed_charges:
            res.findings.append(Finding(
                error_type=ErrorType.UNAUTHORIZED_CHARGE, rule_id="unauthorized_charge", line_no=line.line_no,
                charge_type=line.charge_type, expected=Decimal("0"), billed=q(line.amount / fx),
                difference=q(line.amount / fx), currency=c.currency, confidence=conf,
                message=f"{line.charge_type.value} is not a permitted charge under contract {c.contract_id}.",
                evidence=Evidence(
                    contract_clause=f"Contract {c.contract_id} permits only: "
                                    + ", ".join(a.value for a in c.allowed_charges),
                    invoice_text=ltext)))
            return

        rates = self._rates_for(inv, line.charge_type)
        applicable = [r for r in rates if r.covers(inv.ship_date)]
        if not applicable:
            res.review_notes.append(
                f"Line {line.line_no}: no contract rate for {line.charge_type.value} on "
                f"{inv.origin}->{inv.destination} {inv.container_type} at {inv.ship_date}.")
            return
        rate = applicable[0]

        if line.charge_type in DND:
            self._check_dnd(inv, line, rate, fx, conf, ltext, res)
        else:
            self._check_rate(inv, line, rate, rates, fx, conf, ltext, res)

    def _check_rate(self, inv, line, rate, all_rates, fx, conf, ltext, res) -> None:
        c = self.c
        billed = line.unit_rate / fx
        if billed <= rate.rate * (1 + RATE_TOL) + CENT:
            expected_qty = {RateUnit.PER_CONTAINER: inv.container_count, RateUnit.PER_BL: 1}.get(rate.unit)
            if expected_qty is not None and line.quantity > expected_qty:
                res.review_notes.append(
                    f"Line {line.line_no}: quantity {line.quantity} exceeds expected {expected_qty} ({rate.unit.value}).")
            return
        stale = next((r for r in all_rates if r is not rate and abs(billed - r.rate) <= r.rate * RATE_TOL + CENT), None)
        etype = ErrorType.EXPIRED_RATE if stale else ErrorType.WRONG_RATE
        msg = (f"Billed rate {_fmt(billed, c.currency)} matches the rate valid {stale.valid_from} to {stale.valid_to}, "
               f"but the shipment date {inv.ship_date} falls under {_fmt(rate.rate, c.currency)}."
               if stale else
               f"Billed rate {_fmt(billed, c.currency)} exceeds contracted {_fmt(rate.rate, c.currency)}.")
        clause = _rate_clause(c, rate) + (f"; superseded rate: {_rate_clause(c, stale)}" if stale else "")
        res.findings.append(Finding(
            error_type=etype, rule_id=etype.value, line_no=line.line_no, charge_type=line.charge_type,
            expected=q(rate.rate), billed=q(billed), difference=q((billed - rate.rate) * line.quantity),
            currency=c.currency, confidence=min(conf, self._conf(inv, "ship_date", "origin", "destination", "container_type")),
            message=msg, evidence=Evidence(contract_clause=clause, invoice_text=ltext)))

    def _check_dnd(self, inv, line, rate, fx, conf, ltext, res) -> None:
        c = self.c
        if line.charge_type == ChargeType.DETENTION:
            start, end, label = inv.equipment_out, inv.equipment_in, "equipment out/in"
        else:
            start, end, label = inv.discharge_date, inv.pickup_date, "discharge/pickup"
        if start is None or end is None:
            res.review_notes.append(f"Line {line.line_no}: {line.charge_type.value} billed but {label} dates missing.")
            return
        used = (end - start).days
        free = rate.free_days or 0
        chargeable_days = max(0, used - free)
        expected_qty = Decimal(chargeable_days * inv.container_count)
        expected = expected_qty * rate.rate
        billed = line.quantity * line.unit_rate / fx
        if billed <= expected * (1 + RATE_TOL) + CENT:
            return
        res.findings.append(Finding(
            error_type=ErrorType.DETENTION_DEMURRAGE, rule_id=f"{line.charge_type.value.lower()}_days",
            line_no=line.line_no, charge_type=line.charge_type, expected=q(expected), billed=q(billed),
            difference=q(billed - expected), currency=c.currency,
            confidence=min(conf, self._conf(inv, "equipment_out", "equipment_in", "discharge_date", "pickup_date")),
            message=(f"{line.charge_type.value.title()}: {used} days used ({start} to {end}), {free} free days -> "
                     f"{chargeable_days} chargeable days x {inv.container_count} container(s) x "
                     f"{_fmt(rate.rate, c.currency)} = {_fmt(expected, c.currency)}; billed {_fmt(billed, c.currency)}."),
            evidence=Evidence(contract_clause=_rate_clause(c, rate), invoice_text=ltext)))

    # ------------------------------------------------------------ totals
    def _check_totals(self, inv: Invoice, fx: Decimal, res: AuditResult) -> None:
        c, ccy = self.c, inv.currency
        conf = self._conf(inv, "subtotal", "tax_amount", "total")
        lines_sum = sum((l.amount for l in inv.lines), Decimal("0"))
        if inv.subtotal - lines_sum > MATH_TOL:
            res.findings.append(Finding(
                error_type=ErrorType.CALCULATION_ERROR, rule_id="subtotal_mismatch", expected=q(lines_sum / fx),
                billed=q(inv.subtotal / fx), difference=q((inv.subtotal - lines_sum) / fx), currency=c.currency,
                confidence=conf, message="Subtotal exceeds the sum of line amounts.",
                evidence=Evidence(contract_clause="Subtotal must equal the sum of line amounts.",
                                  invoice_text=f"Sum of lines {_fmt(lines_sum, ccy)}; subtotal {_fmt(inv.subtotal, ccy)}")))

        allowed_rate = c.tax_rates.get(ccy, Decimal("0"))
        allowed_tax = inv.subtotal * allowed_rate
        if inv.tax_amount - allowed_tax > MATH_TOL:
            res.findings.append(Finding(
                error_type=ErrorType.CURRENCY_TAX, rule_id="tax_rate", expected=q(allowed_tax / fx),
                billed=q(inv.tax_amount / fx), difference=q((inv.tax_amount - allowed_tax) / fx), currency=c.currency,
                confidence=min(conf, self._conf(inv, "tax_amount")),
                message=f"Tax of {_fmt(inv.tax_amount, ccy)} exceeds the contractual {allowed_rate:.0%} "
                        f"({_fmt(allowed_tax, ccy)}).",
                evidence=Evidence(contract_clause=f"Contract {c.contract_id}: tax on {ccy} invoices = {allowed_rate:.0%}",
                                  invoice_text=f"Tax line {_fmt(inv.tax_amount, ccy)}"
                                               + (f" ({inv.tax_rate:.0%})" if inv.tax_rate is not None else ""))))

        expected_total = inv.subtotal + inv.tax_amount
        if inv.total - expected_total > MATH_TOL:
            res.findings.append(Finding(
                error_type=ErrorType.CALCULATION_ERROR, rule_id="total_mismatch", expected=q(expected_total / fx),
                billed=q(inv.total / fx), difference=q((inv.total - expected_total) / fx), currency=c.currency,
                confidence=conf, message="Invoice total exceeds subtotal + tax.",
                evidence=Evidence(contract_clause="Total must equal subtotal plus tax.",
                                  invoice_text=f"Subtotal {_fmt(inv.subtotal, ccy)} + tax {_fmt(inv.tax_amount, ccy)} "
                                               f"vs total {_fmt(inv.total, ccy)}")))


def audit_invoice(invoice: Invoice, contract: Contract, history: list[PriorInvoice] | None = None) -> AuditResult:
    return RuleEngine(contract).audit(invoice, history)


