"""Four invoice layouts rendered with ReportLab.

Layouts differ in field labels, date formats, number grouping, column order,
fonts and whether charge codes are printed, so extraction is actually exercised.
All documents carry a "SYNTHETIC" footer - they are not real carrier invoices.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from freight_audit.models import Invoice
from freight_audit.normalize import PORT_NAMES


@dataclass
class Display:
    """Things printed on the invoice that the auditor doesn't need to extract."""
    carrier_address: str
    shipper_name: str
    shipper_address: str
    vessel: str
    voyage: str
    container_numbers: list[str]
    charge_codes: dict[int, str] = field(default_factory=dict)  # line_no -> code


def fmt_num(x: Decimal, indian: bool = False) -> str:
    s = f"{x:,.2f}"
    if not indian:
        return s
    whole, frac = f"{x:.2f}".split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}{whole}.{frac}"


CTYPE_LONG = {"20GP": "20' Dry Standard", "40GP": "40' Dry Standard", "40HC": "40' High Cube"}

TEMPLATES = {
    "T1": dict(
        font="Helvetica", title="FREIGHT INVOICE", datefmt="%Y-%m-%d", indian=False,
        labels=dict(invoice_number="Invoice No.", invoice_date="Invoice Date", contract_ref="Contract Ref",
                    bl_number="B/L No.", origin="Port of Loading", destination="Port of Discharge",
                    equipment="Equipment", ship_date="Sailing Date", currency="Currency",
                    exchange_rate="Exchange Rate", equipment_out="Equipment Out", equipment_in="Equipment Returned",
                    discharge_date="Discharge Date", pickup_date="Delivery Date"),
        columns=["#", "Description", "Qty", "Rate", "Amount"],
        subtotal="Subtotal", total="Total Amount Due"),
    "T2": dict(
        font="Times-Roman", title="TAX INVOICE", datefmt="%d/%m/%Y", indian=False,
        labels=dict(invoice_number="Inv #", invoice_date="Date of Issue", contract_ref="Agreement No",
                    bl_number="Bill of Lading", origin="POL", destination="POD",
                    container_type="Container Type", container_count="No. of Containers", ship_date="ETD",
                    currency="Billing Currency", exchange_rate="ROE", equipment_out="Gate Out (Empty)",
                    equipment_in="Gate In (Empty)", discharge_date="Vessel Discharge", pickup_date="Gate Out (Full)"),
        columns=["Code", "Charge Description", "Amount", "Unit Price", "Units"],
        subtotal="Net Amount", total="Invoice Total"),
    "T3": dict(
        font="Courier", title="BILL OF CHARGES", datefmt="%d-%b-%Y", indian=True,
        labels=dict(invoice_number="Bill No", invoice_date="Bill Date", contract_ref="Rate Agreement",
                    bl_number="BL Number", origin="Origin", destination="Destination", equipment="Equipment",
                    ship_date="Vessel Sailed", currency="Currency", exchange_rate="Exchange Rate",
                    equipment_out="Container Pick-up", equipment_in="Container Return",
                    discharge_date="Vessel Arrival", pickup_date="Cargo Delivered"),
        columns=["Charge", "Basis", "Unit Rate", "Total"],
        subtotal="Sub Total", total="Amount Payable"),
    "T4": dict(
        font="Helvetica", title="INVOICE", datefmt="%d.%m.%Y", indian=False,
        labels=dict(invoice_number="Invoice Number", invoice_date="Invoice Date", contract_ref="Contract",
                    bl_number="B/L", origin="Load Port", destination="Discharge Port",
                    container_type="Equipment Type", container_count="Quantity", ship_date="Shipped On",
                    currency="Currency", exchange_rate="Rate of Exchange", equipment_out="Empty Release",
                    equipment_in="Empty Return", discharge_date="Discharged", pickup_date="Collected"),
        columns=["Pos.", "Charge", "Code", "Quantity", "Price", "Line Total"],
        subtotal="Total excl. Tax", total="Total incl. Tax"),
    # Held-out layout: only appears in the test split. Unseen labels, no vertical rules,
    # unseen charge wording (see generator.HELDOUT_DESCRIPTIONS).
    "T5": dict(
        font="Helvetica", title="STATEMENT OF FREIGHT CHARGES", datefmt="%b %d, %Y", indian=False, heldout=True,
        labels=dict(invoice_number="Document No", invoice_date="Issued", contract_ref="Contract #",
                    bl_number="Transport Document", origin="Place of Loading", destination="Place of Delivery",
                    equipment="Units / Size", ship_date="Departure", currency="Payable In",
                    exchange_rate="Conversion", equipment_out="Empty Pickup", equipment_in="Empty Drop-off",
                    discharge_date="Arrived", pickup_date="Released to Consignee"),
        columns=["Item", "Service", "Count", "Each", "Extended"],
        subtotal="Charges", total="Balance Due"),
}


def _port(code: str, tid: str) -> str:
    name = PORT_NAMES.get(code, code)
    if tid == "T5":
        return f"{name}, {code[:2]}"
    return f"{name} ({code})" if tid in ("T1", "T3", "T4") else f"{name.upper()}, {code[:2]} ({code})"


def render_invoice(inv: Invoice, disp: Display, tid: str) -> bytes:
    t = TEMPLATES[tid]
    lab, font, indian = t["labels"], t["font"], t["indian"] and inv.currency == "INR"
    d = lambda x: x.strftime(t["datefmt"])  # noqa: E731
    n = lambda x: fmt_num(x, indian)  # noqa: E731
    bold = {"Helvetica": "Helvetica-Bold", "Times-Roman": "Times-Bold", "Courier": "Courier-Bold"}[font]

    styles = getSampleStyleSheet()
    h = styles["Title"].clone("h", fontName=bold, fontSize=16, alignment=0)
    body = styles["Normal"].clone("b", fontName=font, fontSize=8.5, leading=11)
    small = styles["Normal"].clone("s", fontName=font, fontSize=7, textColor=colors.grey)

    story = [Paragraph(inv.carrier, h), Paragraph(disp.carrier_address, body), Spacer(1, 4 * mm),
             Paragraph(f"<b>{t['title']}</b>", body), Spacer(1, 2 * mm),
             Paragraph(f"Bill To: {disp.shipper_name}, {disp.shipper_address}", body), Spacer(1, 3 * mm)]

    kv: list[tuple[str, str]] = [
        (lab["invoice_number"], inv.invoice_number), (lab["invoice_date"], d(inv.invoice_date)),
        (lab["contract_ref"], inv.contract_ref or ""), (lab["bl_number"], inv.bl_number),
        (lab["origin"], _port(inv.origin, tid)), (lab["destination"], _port(inv.destination, tid)),
    ]
    if "equipment" in lab:
        kv.append((lab["equipment"], f"{inv.container_count} x {inv.container_type}"))
    else:
        kv += [(lab["container_type"], CTYPE_LONG[inv.container_type]),
               (lab["container_count"], str(inv.container_count))]
    kv += [(lab["ship_date"], d(inv.ship_date)), ("Vessel / Voyage", f"{disp.vessel} / {disp.voyage}"),
           (lab["currency"], inv.currency)]
    if inv.exchange_rate is not None:
        kv.append((lab["exchange_rate"],
                   f"1 USD = {inv.exchange_rate} INR" if tid in ("T1", "T3", "T5") else str(inv.exchange_rate)))
    if inv.equipment_out:
        kv += [(lab["equipment_out"], d(inv.equipment_out)), (lab["equipment_in"], d(inv.equipment_in))]
    if inv.discharge_date:
        kv += [(lab["discharge_date"], d(inv.discharge_date)), (lab["pickup_date"], d(inv.pickup_date))]
    if len(kv) % 2:
        kv.append(("", ""))
    rows = [[kv[i][0], kv[i][1], kv[i + 1][0], kv[i + 1][1]] for i in range(0, len(kv), 2)]
    rule = ("LINEBELOW", (0, 0), (-1, -1), 0.3, colors.grey) if t.get("heldout") else         ("GRID", (0, 0), (-1, -1), 0.4, colors.grey)
    hdr = Table(rows, colWidths=[32 * mm, 55 * mm, 32 * mm, 55 * mm])
    hdr.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), font, 8), rule,
                             ("FONT", (0, 0), (0, -1), bold, 8), ("FONT", (2, 0), (2, -1), bold, 8)]))
    story += [hdr, Spacer(1, 3 * mm),
              Paragraph("Containers: " + ", ".join(disp.container_numbers), small), Spacer(1, 3 * mm)]

    ccy = inv.currency
    rows = [list(t["columns"])]
    for ln in inv.lines:
        code = disp.charge_codes.get(ln.line_no, "")
        q = str(int(ln.quantity)) if ln.quantity == ln.quantity.to_integral() else str(ln.quantity)
        if tid == "T1":
            rows.append([str(ln.line_no), ln.description, q, n(ln.unit_rate), n(ln.amount)])
        elif tid == "T2":
            rows.append([code, ln.description, n(ln.amount), n(ln.unit_rate), q])
        elif tid == "T3":
            basis = "DAY" if ln.description and any(k in ln.description.lower() for k in ("detention", "demurrage")) else "UNIT"
            rows.append([ln.description, f"{q} x {basis}", f"{ccy} {n(ln.unit_rate)}", f"{ccy} {n(ln.amount)}"])
        elif tid == "T4":
            rows.append([f"{ln.line_no * 10}", ln.description, code, q, n(ln.unit_rate), n(ln.amount)])
        else:
            rows.append([f"{ln.line_no:02d}", ln.description, q, n(ln.unit_rate), n(ln.amount)])
    widths = {"T1": [10, 84, 16, 30, 34], "T2": [16, 80, 30, 30, 18], "T3": [70, 26, 38, 40],
              "T4": [14, 70, 16, 20, 26, 28], "T5": [12, 86, 16, 30, 34]}[tid]
    lt = Table(rows, colWidths=[w * mm for w in widths], repeatRows=1)
    lt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), font, 8), ("FONT", (0, 0), (-1, 0), bold, 8), rule,
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef5"))]))
    story += [lt, Spacer(1, 3 * mm)]

    tax_pct = f"{(inv.tax_rate or Decimal(0)) * 100:.0f}%"
    tax_label = f"IGST @ {tax_pct}" if ccy == "INR" else f"Tax ({tax_pct})"
    if tid == "T5":
        tax_label = f"Levy {tax_pct}"
    tot = Table([[t["subtotal"], f"{ccy} {n(inv.subtotal)}"], [tax_label, f"{ccy} {n(inv.tax_amount)}"],
                 [t["total"], f"{ccy} {n(inv.total)}"]], colWidths=[50 * mm, 40 * mm], hAlign="RIGHT")
    tot.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), font, 8.5), ("FONT", (0, 2), (-1, 2), bold, 9), rule]))
    story += [tot, Spacer(1, 6 * mm),
              Paragraph("Payment due within 30 days. Please quote the invoice number on remittance.", body),
              Spacer(1, 4 * mm),
              Paragraph("SYNTHETIC DOCUMENT - generated for software testing. Not a real invoice.", small)]

    buf = BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm,
                      bottomMargin=12 * mm, title=f"Invoice {inv.invoice_number}").build(story)
    return buf.getvalue()


def rasterize(pdf_bytes: bytes, dpi: int = 110) -> bytes:
    """Turn a text PDF into an image-only PDF, simulating a scan (no text layer)."""
    import fitz  # PyMuPDF

    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    out = fitz.open()
    for page in src:
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        p = out.new_page(width=page.rect.width, height=page.rect.height)
        p.insert_image(p.rect, pixmap=pix)
    return out.tobytes()


