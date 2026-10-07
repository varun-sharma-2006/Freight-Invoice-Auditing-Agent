"""Domain models shared by every layer (extraction, rules, API, eval).

Money is always Decimal. Rates in a contract are expressed in the contract
currency; invoices may be billed in another currency with a stated exchange
rate ("1 USD = 83.25 INR" -> exchange_rate = 83.25).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class ChargeType(str, Enum):
    BASE_FREIGHT = "BASE_FREIGHT"
    FUEL_SURCHARGE = "FUEL_SURCHARGE"  # BAF / bunker
    THC_ORIGIN = "THC_ORIGIN"
    THC_DEST = "THC_DEST"
    DOC_FEE = "DOC_FEE"
    ISPS = "ISPS"
    SEAL_FEE = "SEAL_FEE"
    DETENTION = "DETENTION"
    DEMURRAGE = "DEMURRAGE"
    PEAK_SEASON = "PEAK_SEASON"
    CONGESTION = "CONGESTION"
    EMERGENCY_BUNKER = "EMERGENCY_BUNKER"
    WAR_RISK = "WAR_RISK"
    CURRENCY_ADJUSTMENT = "CURRENCY_ADJUSTMENT"
    UNKNOWN = "UNKNOWN"


class RateUnit(str, Enum):
    PER_CONTAINER = "per_container"
    PER_BL = "per_bl"
    PER_CONTAINER_DAY = "per_container_day"


class ErrorType(str, Enum):
    WRONG_RATE = "wrong_rate"
    DUPLICATE_LINE = "duplicate_line"
    DUPLICATE_INVOICE = "duplicate_invoice"
    UNAUTHORIZED_CHARGE = "unauthorized_charge"
    CALCULATION_ERROR = "calculation_error"
    DETENTION_DEMURRAGE = "detention_demurrage"
    EXPIRED_RATE = "expired_rate"
    CURRENCY_TAX = "currency_tax"


# ---------------------------------------------------------------- contract
class ContractRate(BaseModel):
    origin: str  # UN/LOCODE, e.g. INNSA
    destination: str
    container_type: str  # 20GP / 40GP / 40HC
    charge_type: ChargeType
    rate: Decimal
    unit: RateUnit
    free_days: int | None = None
    valid_from: date
    valid_to: date

    def covers(self, d: date) -> bool:
        return self.valid_from <= d <= self.valid_to


class Contract(BaseModel):
    contract_id: str
    carrier: str
    shipper: str
    currency: str = "USD"
    valid_from: date
    valid_to: date
    # Tax rate the contract allows, keyed by invoice currency (e.g. {"USD": 0, "INR": 0.05}).
    tax_rates: dict[str, Decimal] = Field(default_factory=dict)
    # Agreed exchange rates: 1 unit of contract currency = X units of the key currency.
    fx_rates: dict[str, Decimal] = Field(default_factory=dict)
    fx_tolerance: Decimal = Decimal("0.005")
    allowed_charges: list[ChargeType]
    rates: list[ContractRate]


# ---------------------------------------------------------------- invoice
class InvoiceLine(BaseModel):
    line_no: int
    description: str
    charge_code: str | None = None
    charge_type: ChargeType = ChargeType.UNKNOWN
    mapping_confidence: float = 1.0
    quantity: Decimal
    unit_rate: Decimal
    amount: Decimal


class Invoice(BaseModel):
    invoice_number: str
    carrier: str
    invoice_date: date
    contract_ref: str | None = None
    bl_number: str
    origin: str
    destination: str
    container_type: str
    container_count: int
    ship_date: date
    currency: str
    exchange_rate: Decimal | None = None
    equipment_out: date | None = None
    equipment_in: date | None = None
    discharge_date: date | None = None
    pickup_date: date | None = None
    lines: list[InvoiceLine]
    subtotal: Decimal
    tax_rate: Decimal | None = None
    tax_amount: Decimal = Decimal("0")
    total: Decimal
    # 0..1 per header field; fields below the review threshold are not trusted.
    field_confidence: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------- findings
class Evidence(BaseModel):
    contract_clause: str
    invoice_text: str


class Finding(BaseModel):
    error_type: ErrorType
    rule_id: str
    line_no: int | None = None
    charge_type: ChargeType | None = None
    expected: Decimal | None = None
    billed: Decimal | None = None
    # Overcharge expressed in the contract currency.
    difference: Decimal = Decimal("0")
    currency: str = "USD"
    confidence: float = 1.0
    message: str
    evidence: Evidence


class AuditResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_notes) or any(f.confidence < 0.8 for f in self.findings)

    @property
    def total_overcharge(self) -> Decimal:
        return sum((f.difference for f in self.findings), Decimal("0"))
