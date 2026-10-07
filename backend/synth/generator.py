"""Synthetic dataset generator: contracts -> invoices -> injected errors with labels.

    python -m synth.generator --out ../data/synthetic --dev 120 --test 240 --seed 7

Writes, per split, invoice PDFs, `labels.jsonl` (ground-truth invoice fields and
injected errors with their overcharge in contract currency) and the contracts.
Every carrier, shipper, vessel and number here is fictional.
"""
from __future__ import annotations

import argparse
import json
import random
import string
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from faker import Faker

from freight_audit.models import (
    ChargeType as CT, Contract, ContractRate, ErrorType as ET, Invoice, InvoiceLine, RateUnit,
)

from .templates import TEMPLATES, Display, rasterize, render_invoice

D = Decimal
CENT = D("0.01")


def money(x) -> Decimal:
    return D(x).quantize(CENT, rounding=ROUND_HALF_UP)


CARRIERS = [
    # name, invoice-number style, B/L prefix, container owner code
    ("Oceanic Meridian Lines", "OML-INV-{y}-{n:06d}", "OMLU", "OMLU"),
    ("BlueWake Container Shipping", "BW/{yy}/{n:05d}", "BWCS", "BWKU"),
    ("Harborstar Logistics", "HSL{yy}{n:07d}", "HSTL", "HSTU"),
    ("Tidewater Global Freight", "TGF-{yy}-{n:05d}", "TDWG", "TDWU"),
]
ORIGINS = ["INNSA", "INMUN", "INMAA"]
DESTS = ["NLRTM", "DEHAM", "AEJEA", "USNYC", "SGSIN", "BEANR", "GBFXT"]
CTYPES = ["20GP", "40GP", "40HC"]
ALLOWED = [CT.BASE_FREIGHT, CT.FUEL_SURCHARGE, CT.THC_ORIGIN, CT.THC_DEST, CT.DOC_FEE, CT.ISPS, CT.SEAL_FEE,
           CT.DETENTION, CT.DEMURRAGE]
UNAUTHORIZED = [CT.PEAK_SEASON, CT.CONGESTION, CT.EMERGENCY_BUNKER, CT.WAR_RISK, CT.CURRENCY_ADJUSTMENT]

DESCRIPTIONS = {
    CT.BASE_FREIGHT: ["Ocean Freight", "Basic Ocean Freight", "Sea Freight Charges", "Base Freight Rate", "O/F - Ocean Freight"],
    CT.FUEL_SURCHARGE: ["Bunker Adjustment Factor (BAF)", "Fuel Surcharge", "Bunker adj.", "BAF - Bunker Surcharge"],
    CT.THC_ORIGIN: ["Terminal Handling Charge - Origin", "THC at POL", "Origin Terminal Handling", "Export THC",
                    "Terminal Hdlg Chg (Origin)"],
    CT.THC_DEST: ["Terminal Handling Charge - Destination", "THC at POD", "Destination Terminal Handling", "Import THC",
                  "Terminal Hdlg Chg (Dest)"],
    CT.DOC_FEE: ["Documentation Fee", "B/L Fee", "Bill of Lading Fee", "Docs Charge", "Export Documentation"],
    CT.ISPS: ["ISPS Surcharge", "Port Security Fee", "ISPS Charge", "Intl Ship & Port Security"],
    CT.SEAL_FEE: ["Seal Fee", "Container Seal Charge", "High Security Seal"],
    CT.DETENTION: ["Detention Charges", "Container Detention", "Equipment Detention", "Detention (beyond free time)"],
    CT.DEMURRAGE: ["Demurrage Charges", "Terminal Demurrage", "Container Demurrage", "Demurrage (port storage)"],
    CT.PEAK_SEASON: ["Peak Season Surcharge", "PSS", "Peak Season Adj."],
    CT.CONGESTION: ["Port Congestion Surcharge", "Congestion Fee", "Congestion Surcharge"],
    CT.EMERGENCY_BUNKER: ["Emergency Bunker Surcharge", "Emergency Fuel Surcharge"],
    CT.WAR_RISK: ["War Risk Surcharge", "War Risk Premium"],
    CT.CURRENCY_ADJUSTMENT: ["Currency Adjustment Factor", "CAF Surcharge"],
}
# Wording used only by the held-out T5 layout (never seen while developing the mapper).
HELDOUT_DESCRIPTIONS = {
    CT.BASE_FREIGHT: ["Linehaul - Port to Port", "Freight (all-in base)", "Main Carriage"],
    CT.FUEL_SURCHARGE: ["Marine Fuel Recovery", "Bunker Recovery Charge", "Fuel Recovery"],
    CT.THC_ORIGIN: ["Origin Port Handling", "Load Port Handling", "Export Terminal Fee"],
    CT.THC_DEST: ["Destination Port Handling", "Discharge Port Handling", "Import Terminal Fee"],
    CT.DOC_FEE: ["Documentation Charges", "Transport Document Issuance", "Paperwork Fee"],
    CT.ISPS: ["Security Surcharge (ISPS)", "Facility Security Charge"],
    CT.SEAL_FEE: ["Equipment Seal", "Bolt Seal"],
    CT.DETENTION: ["Container Retention", "Equipment Use Beyond Free Time", "Detention"],
    CT.DEMURRAGE: ["Port Storage", "Quay Rent", "Demurrage"],
    CT.PEAK_SEASON: ["High Demand Premium", "Peak Season Surcharge"],
    CT.CONGESTION: ["Port Delay Recovery", "Congestion Recovery"],
    CT.EMERGENCY_BUNKER: ["Emergency Fuel Recovery"],
    CT.WAR_RISK: ["Conflict Zone Premium", "War Risk Surcharge"],
    CT.CURRENCY_ADJUSTMENT: ["FX Adjustment", "Currency Adjustment Factor"],
}
CODES = {CT.BASE_FREIGHT: "OFR", CT.FUEL_SURCHARGE: "BAF", CT.THC_ORIGIN: "THO", CT.THC_DEST: "THD",
         CT.DOC_FEE: "DOC", CT.ISPS: "ISP", CT.SEAL_FEE: "SEA", CT.DETENTION: "DET", CT.DEMURRAGE: "DEM",
         CT.PEAK_SEASON: "PSS", CT.CONGESTION: "CGS", CT.EMERGENCY_BUNKER: "EBS", CT.WAR_RISK: "WRS",
         CT.CURRENCY_ADJUSTMENT: "CAF"}
VESSELS = ["MV Coral Meridian", "MV Northern Lark", "MV Saffron Tide", "MV Aurora Bay", "MV Kestrel Star",
           "MV Indigo Crest", "MV Monsoon Pearl"]


# ------------------------------------------------------------------ contracts
def make_contract(rng: random.Random, idx: int, year: int = 2026) -> Contract:
    carrier = CARRIERS[idx][0]
    mid = date(year, 7, 1)
    p1 = (date(year, 1, 1), mid - timedelta(days=1))
    p2 = (mid, date(year, 12, 31))
    rates: list[ContractRate] = []
    lanes = [(o, d) for o in ORIGINS for d in DESTS]
    for o, d in rng.sample(lanes, 4):
        for ct in CTYPES:
            big = ct != "20GP"
            base = D(rng.randint(1500, 3400) if big else rng.randint(850, 1900))
            baf = money(base * D(rng.uniform(0.14, 0.26)))
            fixed = {
                CT.THC_ORIGIN: (D(rng.randint(150, 190) if big else rng.randint(100, 135)), RateUnit.PER_CONTAINER, None),
                CT.THC_DEST: (D(rng.randint(220, 320) if big else rng.randint(150, 210)), RateUnit.PER_CONTAINER, None),
                CT.DOC_FEE: (D(rng.choice([50, 55, 60, 65, 75])), RateUnit.PER_BL, None),
                CT.ISPS: (D(rng.choice([10, 12, 15])), RateUnit.PER_CONTAINER, None),
                CT.SEAL_FEE: (D(rng.choice([8, 10, 12])), RateUnit.PER_CONTAINER, None),
                CT.DETENTION: (D(rng.randint(40, 70) if big else rng.randint(22, 40)), RateUnit.PER_CONTAINER_DAY,
                               rng.choice([7, 10, 14])),
                CT.DEMURRAGE: (D(rng.randint(60, 95) if big else rng.randint(30, 55)), RateUnit.PER_CONTAINER_DAY,
                               rng.choice([4, 5, 7])),
            }
            # Market softened mid-year: H1 base freight and BAF were 6-15% higher than H2.
            for ct_, val in ((CT.BASE_FREIGHT, base), (CT.FUEL_SURCHARGE, baf)):
                h1 = money(val * D(1 + rng.uniform(0.06, 0.15)))
                rates.append(ContractRate(origin=o, destination=d, container_type=ct, charge_type=ct_, rate=h1,
                                          unit=RateUnit.PER_CONTAINER, valid_from=p1[0], valid_to=p1[1]))
                rates.append(ContractRate(origin=o, destination=d, container_type=ct, charge_type=ct_, rate=money(val),
                                          unit=RateUnit.PER_CONTAINER, valid_from=p2[0], valid_to=p2[1]))
            for ct_, (val, unit, free) in fixed.items():
                rates.append(ContractRate(origin=o, destination=d, container_type=ct, charge_type=ct_, rate=money(val),
                                          unit=unit, free_days=free, valid_from=p1[0], valid_to=p2[1]))
    return Contract(
        contract_id=f"SC-{CARRIERS[idx][2]}-{year}-{idx + 1:02d}", carrier=carrier,
        shipper="Acme Exports Pvt Ltd (fictional)", currency="USD", valid_from=p1[0], valid_to=p2[1],
        tax_rates={"USD": D("0"), "INR": D("0.05")},
        fx_rates={"INR": money(D(rng.uniform(83.0, 88.0)))},
        allowed_charges=ALLOWED, rates=rates)


# ------------------------------------------------------------------ invoices
@dataclass
class Draft:
    """A line under construction, in contract currency (USD) until converted."""
    ct: CT
    qty: Decimal
    rate_usd: Decimal
    desc: str
    labels: list[dict] = field(default_factory=list)
    unit_rate: Decimal = D(0)
    amount: Decimal = D(0)
    targeted: bool = False


@dataclass
class Generated:
    invoice: Invoice
    display: Display
    labels: list[dict]
    template: str
    scanned: bool = False


def iso6346(owner: str, rng: random.Random) -> str:
    vals, v = {}, 10
    for ch in string.ascii_uppercase:
        if v % 11 == 0:
            v += 1
        vals[ch] = v
        v += 1
    serial = f"{rng.randint(0, 999999):06d}"
    code = owner + serial
    total = sum((vals[c] if c.isalpha() else int(c)) * 2 ** i for i, c in enumerate(code))
    return f"{code}{total % 11 % 10}"


def _rate(c: Contract, o, d, ctype, ct, when: date) -> ContractRate:
    return next(r for r in c.rates if (r.origin, r.destination, r.container_type, r.charge_type) == (o, d, ctype, ct)
                and r.covers(when))


def _other_period_rate(c: Contract, o, d, ctype, ct, when: date) -> ContractRate | None:
    return next((r for r in c.rates if (r.origin, r.destination, r.container_type, r.charge_type) == (o, d, ctype, ct)
                 and not r.covers(when)), None)


class InvoiceFactory:
    def __init__(self, rng: random.Random, contracts: list[Contract], faker: Faker):
        self.rng, self.contracts, self.fk = rng, contracts, faker
        self.counters = {c.carrier: rng.randint(1000, 9000) for c in contracts}

    def _number(self, idx: int, d: date) -> str:
        c = self.contracts[idx]
        self.counters[c.carrier] += self.rng.randint(1, 40)
        return CARRIERS[idx][1].format(y=d.year, yy=d.strftime("%y"), n=self.counters[c.carrier])

    def make(self, error_count: int, template: str) -> Generated:
        rng = self.rng
        idx = rng.randrange(len(self.contracts))
        c = self.contracts[idx]
        lanes = sorted({(r.origin, r.destination) for r in c.rates})
        o, d = rng.choice(lanes)
        ctype = rng.choice(CTYPES)
        count = rng.choice([1, 1, 2, 2, 3, 4])
        ship = c.valid_from + timedelta(days=rng.randint(5, (c.valid_to - c.valid_from).days - 25))
        currency = "INR" if rng.random() < 0.4 else "USD"
        agreed_fx = c.fx_rates["INR"]

        drafts: list[Draft] = []
        vocab = HELDOUT_DESCRIPTIONS if template == "T5" else DESCRIPTIONS

        def add(ct: CT, qty=None, rate=None):
            r = _rate(c, o, d, ctype, ct, ship)
            if qty is None:
                qty = 1 if r.unit == RateUnit.PER_BL else count
            drafts.append(Draft(ct, D(qty), rate if rate is not None else r.rate, rng.choice(vocab[ct])))
            return drafts[-1]

        add(CT.BASE_FREIGHT)
        add(CT.FUEL_SURCHARGE)
        add(CT.THC_ORIGIN)
        if rng.random() < 0.6:
            add(CT.THC_DEST)
        add(CT.DOC_FEE)
        if rng.random() < 0.5:
            add(CT.ISPS)
        if rng.random() < 0.4:
            add(CT.SEAL_FEE)

        transit = rng.randint(16, 32)
        eq_out = eq_in = disch = pick = None

        def add_detention():
            nonlocal eq_out, eq_in
            r = _rate(c, o, d, ctype, CT.DETENTION, ship)
            used = r.free_days + rng.randint(1, 9)
            eq_out = ship + timedelta(days=transit + rng.randint(1, 3))
            eq_in = eq_out + timedelta(days=used)
            return add(CT.DETENTION, qty=(used - r.free_days) * count)

        def add_demurrage():
            nonlocal disch, pick
            r = _rate(c, o, d, ctype, CT.DEMURRAGE, ship)
            used = r.free_days + rng.randint(1, 6)
            disch = ship + timedelta(days=transit)
            pick = disch + timedelta(days=used)
            return add(CT.DEMURRAGE, qty=(used - r.free_days) * count)

        if rng.random() < 0.35:
            add_detention()
        if rng.random() < 0.25:
            add_demurrage()

        # ---------------- choose errors
        pool = [ET.WRONG_RATE, ET.DUPLICATE_LINE, ET.UNAUTHORIZED_CHARGE, ET.CALCULATION_ERROR,
                ET.DETENTION_DEMURRAGE, ET.EXPIRED_RATE, ET.CURRENCY_TAX]
        if ship < date(ship.year, 7, 1):
            pool.remove(ET.EXPIRED_RATE)  # H1 shipments already carry the higher rate
        errors = rng.sample(pool, error_count)

        def free_line(cts=None) -> Draft | None:
            cands = [x for x in drafts if not x.targeted and (cts is None or x.ct in cts)]
            return rng.choice(cands) if cands else None

        fx = agreed_fx if currency == "INR" else D(1)
        tax_rate = c.tax_rates[currency]
        post: list[tuple] = []  # errors applied after currency conversion

        for e in errors:
            if e == ET.WRONG_RATE:
                ln = free_line([CT.BASE_FREIGHT, CT.FUEL_SURCHARGE, CT.THC_ORIGIN, CT.THC_DEST, CT.DOC_FEE, CT.ISPS])
                if ln is None:
                    continue
                old = ln.rate_usd
                stale = _other_period_rate(c, o, d, ctype, ln.ct, ship)
                while True:  # keep the label honest: never land on the other period's rate by accident
                    ln.rate_usd = money(old * D(1 + rng.uniform(0.05, 0.20)))
                    if stale is None or abs(ln.rate_usd - stale.rate) > stale.rate * D("0.02"):
                        break
                ln.targeted = True
                ln.labels.append(dict(type=e.value, detail=f"rate {old} -> {ln.rate_usd}",
                                      _over_usd=(ln.rate_usd - old) * ln.qty))
            elif e == ET.EXPIRED_RATE:
                ln = free_line([CT.BASE_FREIGHT, CT.FUEL_SURCHARGE])
                if ln is None:
                    continue
                stale = _other_period_rate(c, o, d, ctype, ln.ct, ship)
                old = ln.rate_usd
                ln.rate_usd, ln.targeted = stale.rate, True
                ln.labels.append(dict(type=e.value, detail=f"used {stale.valid_from}..{stale.valid_to} rate {stale.rate}",
                                      _over_usd=(stale.rate - old) * ln.qty))
            elif e == ET.DETENTION_DEMURRAGE:
                ln = free_line([CT.DETENTION, CT.DEMURRAGE])
                if ln is None:
                    if eq_out is None:
                        ln = add_detention()
                    elif disch is None:
                        ln = add_demurrage()
                    else:
                        continue
                ln.targeted = True
                r = _rate(c, o, d, ctype, ln.ct, ship)
                before = ln.qty * ln.rate_usd
                if rng.random() < 0.6:
                    ln.qty = ln.qty + D(r.free_days * count)
                    detail = "free days not deducted"
                else:
                    ln.rate_usd = money(ln.rate_usd * D(rng.choice([1.25, 1.5, 2])))
                    detail = "wrong daily rate"
                ln.labels.append(dict(type=e.value, detail=detail, _over_usd=ln.qty * ln.rate_usd - before))
            elif e == ET.UNAUTHORIZED_CHARGE:
                ct = rng.choice(UNAUTHORIZED)
                per = money(D(rng.randint(40, 320)))
                ln = Draft(ct, D(count), per, rng.choice(vocab[ct]), targeted=True)
                drafts.insert(rng.randint(2, len(drafts)), ln)
                ln.labels.append(dict(type=e.value, detail=ct.value, _over_conv=True))
            elif e == ET.CURRENCY_TAX:
                if currency == "INR" and rng.random() < 0.5:
                    fx = money(agreed_fx * D(1 + rng.uniform(0.02, 0.06)))
                    post.append(("fx", None))
                else:
                    tax_rate = D("0.18") if currency == "INR" else D(rng.choice(["0.05", "0.18"]))
                    post.append(("tax", None))
            elif e == ET.DUPLICATE_LINE:
                post.append(("dup", free_line([CT.BASE_FREIGHT, CT.FUEL_SURCHARGE, CT.THC_ORIGIN, CT.THC_DEST,
                                                CT.DOC_FEE, CT.ISPS, CT.SEAL_FEE])))
                if post[-1][1]:
                    post[-1][1].targeted = True
            elif e == ET.CALCULATION_ERROR:
                if rng.random() < 0.6:
                    ln = free_line()
                    if ln:
                        ln.targeted = True
                    post.append(("calc_line", ln))
                else:
                    post.append(("calc_total", None))

        # ---------------- convert to invoice currency
        for ln in drafts:
            ln.unit_rate = money(ln.rate_usd * fx) if currency == "INR" else ln.rate_usd
            ln.amount = money(ln.qty * ln.unit_rate)
        inv_labels: list[dict] = []
        total_delta = D(0)
        for kind, ln in post:
            if kind == "dup" and ln is not None:
                copy = Draft(ln.ct, ln.qty, ln.rate_usd, ln.desc, unit_rate=ln.unit_rate, amount=ln.amount, targeted=True)
                copy.labels.append(dict(type=ET.DUPLICATE_LINE.value, detail=f"repeat of {ln.ct.value}", _over_conv=True))
                drafts.insert(drafts.index(ln) + 1, copy)
            elif kind == "calc_line" and ln is not None:
                delta = money(D(rng.uniform(10, 200)) * fx)
                ln.amount += delta
                ln.labels.append(dict(type=ET.CALCULATION_ERROR.value, detail="amount != qty x rate",
                                      _over_usd=delta / fx))
            elif kind == "calc_total":
                total_delta = money(D(rng.uniform(10, 250)) * fx)
                inv_labels.append(dict(type=ET.CALCULATION_ERROR.value, line_no=None, detail="total != subtotal + tax",
                                       overcharge=float(money(total_delta / fx))))

        lines = []
        labels: list[dict] = []
        for i, ln in enumerate(drafts, 1):
            lines.append(InvoiceLine(line_no=i, description=ln.desc, charge_code=CODES[ln.ct], charge_type=ln.ct,
                                     quantity=ln.qty, unit_rate=ln.unit_rate, amount=ln.amount))
            for lab in ln.labels:
                over = ln.amount / fx if lab.pop("_over_conv", False) else lab.pop("_over_usd")
                labels.append(dict(type=lab["type"], line_no=i, detail=lab["detail"], overcharge=float(money(over))))

        subtotal = sum((x.amount for x in lines), D(0))
        tax = money(subtotal * tax_rate)
        for kind, _ in post:
            if kind == "fx":
                over = subtotal / agreed_fx - subtotal / fx
                inv_labels.append(dict(type=ET.CURRENCY_TAX.value, line_no=None, detail=f"fx {fx} vs agreed {agreed_fx}",
                                       overcharge=float(money(over))))
            elif kind == "tax":
                right = money(subtotal * c.tax_rates[currency])
                inv_labels.append(dict(type=ET.CURRENCY_TAX.value, line_no=None, detail=f"tax {tax_rate} applied",
                                       overcharge=float(money((tax - right) / fx))))
        labels += inv_labels

        inv_date = ship + timedelta(days=rng.randint(1, 10))
        if eq_in:
            inv_date = max(inv_date, eq_in + timedelta(days=2))
        if pick:
            inv_date = max(inv_date, pick + timedelta(days=2))
        invoice = Invoice(
            invoice_number=self._number(idx, inv_date), carrier=c.carrier, invoice_date=inv_date,
            contract_ref=c.contract_id, bl_number=f"{CARRIERS[idx][2]}{rng.randint(100000000, 999999999)}",
            origin=o, destination=d, container_type=ctype, container_count=count, ship_date=ship, currency=currency,
            exchange_rate=fx if currency == "INR" else None, equipment_out=eq_out, equipment_in=eq_in,
            discharge_date=disch, pickup_date=pick, lines=lines, subtotal=subtotal, tax_rate=tax_rate,
            tax_amount=tax, total=subtotal + tax + total_delta)
        disp = Display(
            carrier_address=self.fk.address().replace("\n", ", "), shipper_name=c.shipper,
            shipper_address=self.fk.address().replace("\n", ", "), vessel=rng.choice(VESSELS),
            voyage=f"{rng.randint(1, 99):03d}{rng.choice('EW')}",
            container_numbers=[iso6346(CARRIERS[idx][3], rng) for _ in range(count)],
            charge_codes={ln.line_no: ln.charge_code for ln in lines})
        return Generated(invoice, disp, labels, template)

    def duplicate_of(self, g: Generated, template: str) -> Generated:
        inv = g.invoice.model_copy(deep=True)
        idx = next(i for i, c in enumerate(self.contracts) if c.carrier == inv.carrier)
        inv.invoice_date = inv.invoice_date + timedelta(days=self.rng.randint(5, 25))
        same_no = self.rng.random() < 0.3
        if not same_no:
            inv.invoice_number = self._number(idx, inv.invoice_date)
        fx = inv.exchange_rate or D(1)
        labels = [dict(lab) for lab in g.labels] + [dict(
            type=ET.DUPLICATE_INVOICE.value, line_no=None, overcharge=float(money(inv.total / fx)),
            detail=f"re-issue of {g.invoice.invoice_number}" + (" (same number)" if same_no else ""))]
        return Generated(inv, g.display, labels, template)


# ------------------------------------------------------------------ dataset
def error_count(rng: random.Random) -> int:
    return rng.choices([0, 1, 2, 3], weights=[35, 35, 20, 10])[0]


def build_split(factory: InvoiceFactory, n: int, rng: random.Random, dup_rate: float, scanned_rate: float,
                heldout_rate: float = 0.0):
    items: list[Generated] = []
    tids = [t for t, cfg in TEMPLATES.items() if not cfg.get("heldout")]
    for _ in range(n):
        tid = "T5" if rng.random() < heldout_rate else rng.choice(tids)
        items.append(factory.make(error_count(rng), tid))
    for _ in range(int(n * dup_rate)):
        pos = rng.randrange(len(items))
        dup = factory.duplicate_of(items[pos], rng.choice(tids))
        items.insert(rng.randint(pos + 1, len(items)), dup)
    for g in items:
        g.scanned = rng.random() < scanned_rate
    return items


def ground_truth(inv: Invoice) -> dict:
    data = json.loads(inv.model_dump_json(exclude={"field_confidence"}))
    return data


def write_split(items: list[Generated], out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "labels.jsonl", "w", encoding="utf-8") as fh:
        for seq, g in enumerate(items, 1):
            fname = f"{seq:04d}_{g.invoice.invoice_number.replace('/', '-')}.pdf"
            pdf = render_invoice(g.invoice, g.display, g.template)
            if g.scanned:
                pdf = rasterize(pdf)
            (out / fname).write_bytes(pdf)
            fh.write(json.dumps(dict(seq=seq, file=fname, template=g.template, scanned=g.scanned,
                                     contract_id=g.invoice.contract_ref, invoice=ground_truth(g.invoice),
                                     errors=g.labels)) + "\n")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="../data/synthetic")
    ap.add_argument("--dev", type=int, default=120)
    ap.add_argument("--test", type=int, default=240)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dup-rate", type=float, default=0.06)
    ap.add_argument("--heldout-rate", type=float, default=0.2,
                    help="fraction of TEST invoices using the held-out T5 layout (never in dev)")
    ap.add_argument("--scanned-rate", type=float, default=0.0,
                    help="fraction of PDFs rasterised to images (needs a vision LLM to read)")
    a = ap.parse_args(argv)

    rng = random.Random(a.seed)
    fk = Faker("en_IN")
    fk.seed_instance(a.seed)
    contracts = [make_contract(rng, i) for i in range(len(CARRIERS))]
    out = Path(a.out)
    (out / "contracts").mkdir(parents=True, exist_ok=True)
    for c in contracts:
        (out / "contracts" / f"{c.contract_id}.json").write_text(c.model_dump_json(indent=2), encoding="utf-8")

    # Separate RNG streams so the test split never shares invoices with dev.
    for split, n, seed, held in (("dev", a.dev, a.seed * 1000 + 1, 0.0),
                                 ("test", a.test, a.seed * 1000 + 2, a.heldout_rate)):
        srng = random.Random(seed)
        items = build_split(InvoiceFactory(srng, contracts, fk), n, srng, a.dup_rate, a.scanned_rate, held)
        write_split(items, out / split)
        n_err = sum(len(g.labels) for g in items)
        print(f"{split}: {len(items)} invoices, {n_err} injected errors, "
              f"{sum(1 for g in items if not g.labels)} clean")


if __name__ == "__main__":
    main()
