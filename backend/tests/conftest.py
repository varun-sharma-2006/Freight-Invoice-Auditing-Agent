import random
from datetime import date
from decimal import Decimal as D

import pytest
from faker import Faker

from freight_audit.config import get_settings
from freight_audit.models import ChargeType as CT, Contract, ContractRate, Invoice, InvoiceLine, RateUnit
from synth.generator import CARRIERS, InvoiceFactory, make_contract


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    """Tests never call a real LLM and never touch the real database."""
    for k in ("GOOGLE_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("EXTRACTOR", "auto")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(scope="session")
def contracts():
    rng = random.Random(11)
    return [make_contract(rng, i) for i in range(len(CARRIERS))]


@pytest.fixture
def factory(contracts):
    rng = random.Random(5)
    fk = Faker("en_IN")
    fk.seed_instance(5)
    return InvoiceFactory(rng, contracts, fk)


@pytest.fixture
def contract():
    """Small hand-written contract: one lane, two rate periods for base freight."""
    h1, h2 = (date(2026, 1, 1), date(2026, 6, 30)), (date(2026, 7, 1), date(2026, 12, 31))
    lane = dict(origin="INNSA", destination="NLRTM", container_type="40HC")
    rates = [
        ContractRate(**lane, charge_type=CT.BASE_FREIGHT, rate=D("2200"), unit=RateUnit.PER_CONTAINER,
                     valid_from=h1[0], valid_to=h1[1]),
        ContractRate(**lane, charge_type=CT.BASE_FREIGHT, rate=D("2000"), unit=RateUnit.PER_CONTAINER,
                     valid_from=h2[0], valid_to=h2[1]),
        ContractRate(**lane, charge_type=CT.FUEL_SURCHARGE, rate=D("400"), unit=RateUnit.PER_CONTAINER,
                     valid_from=h1[0], valid_to=h2[1]),
        ContractRate(**lane, charge_type=CT.DOC_FEE, rate=D("60"), unit=RateUnit.PER_BL,
                     valid_from=h1[0], valid_to=h2[1]),
        ContractRate(**lane, charge_type=CT.DETENTION, rate=D("50"), unit=RateUnit.PER_CONTAINER_DAY, free_days=10,
                     valid_from=h1[0], valid_to=h2[1]),
    ]
    return Contract(contract_id="SC-TEST-01", carrier="Test Line", shipper="Acme", valid_from=h1[0], valid_to=h2[1],
                    tax_rates={"USD": D("0"), "INR": D("0.05")}, fx_rates={"INR": D("85.00")},
                    allowed_charges=[CT.BASE_FREIGHT, CT.FUEL_SURCHARGE, CT.DOC_FEE, CT.DETENTION], rates=rates)


@pytest.fixture
def clean_invoice():
    lines = [
        InvoiceLine(line_no=1, description="Ocean Freight", charge_type=CT.BASE_FREIGHT, quantity=D(2),
                    unit_rate=D("2000"), amount=D("4000")),
        InvoiceLine(line_no=2, description="BAF", charge_type=CT.FUEL_SURCHARGE, quantity=D(2),
                    unit_rate=D("400"), amount=D("800")),
        InvoiceLine(line_no=3, description="B/L Fee", charge_type=CT.DOC_FEE, quantity=D(1),
                    unit_rate=D("60"), amount=D("60")),
        # 14 days used - 10 free = 4 chargeable x 2 containers = 8
        InvoiceLine(line_no=4, description="Detention", charge_type=CT.DETENTION, quantity=D(8),
                    unit_rate=D("50"), amount=D("400")),
    ]
    return Invoice(invoice_number="TL-001", carrier="Test Line", invoice_date=date(2026, 8, 20),
                   contract_ref="SC-TEST-01", bl_number="TL123", origin="INNSA", destination="NLRTM",
                   container_type="40HC", container_count=2, ship_date=date(2026, 8, 1), currency="USD",
                   equipment_out=date(2026, 8, 2), equipment_in=date(2026, 8, 16), lines=lines,
                   subtotal=D("5260"), tax_rate=D(0), tax_amount=D(0), total=D("5260"))
