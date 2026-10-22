from dataclasses import replace
from datetime import date

import pytest

from app.domain.company.profile import CompanyProfile
from app.domain.sales.errors import SalesError
from app.domain.sales.types import LineInput
from app.domain.sales.validation import FinalizeInput, check_credit_lines, check_finalizable

COMPANY = CompanyProfile(
    legal_name="Jansen Webdesign", address_line="Dorpsstraat 1", postal_code="1234 AB", city="Utrecht",
    kvk="12345678", btw_id="NL123456789B01", iban="NL91ABNA0417164300",
)
LINE = LineInput("Website", 1000, 10000, "NL_21", account_id=7)


def data(**kw) -> FinalizeInput:
    base = dict(
        kind="invoice",
        company=COMPANY,
        buyer_name="Klant BV",
        buyer_address_line="Hoofdweg 2",
        buyer_postal_code="1000 AA",
        buyer_city="Amsterdam",
        invoice_date=date(2026, 3, 1),
        due_date=date(2026, 3, 31),
        lines=(LINE,),
        valid_account_ids=frozenset({7}),
        total_incl_cents=12100,
        latest_final_date=None,
        note=None,
    )
    base.update(kw)
    return FinalizeInput(**base)


def err(**kw) -> SalesError:
    with pytest.raises(SalesError) as exc:
        check_finalizable(data(**kw))
    return exc.value


def test_valid_passes():
    check_finalizable(data())


def test_company_incomplete_names_missing_items():
    e = err(company=replace(COMPANY, kvk=None, btw_id=None))
    assert e.code == "MISSING_FIELD" and e.field == "company"
    assert "KvK-nummer" in e.message and "btw-id" in e.message
    assert "Bedrijfsgegevens" in e.message


def test_buyer_address_required():
    e = err(buyer_city=None)
    assert e.field == "contact"
    assert e.message == "Vul het adres van Klant BV in bij Relaties. Het moet op de factuur staan."
    assert err(buyer_address_line=" ").field == "contact"
    assert err(buyer_postal_code=None).field == "contact"


def test_due_date_not_before_invoice_date():
    e = err(due_date=date(2026, 2, 28))
    assert e.field == "due_date"


def test_no_lines():
    assert err(lines=()).field == "lines"


@pytest.mark.parametrize(
    "line,field",
    [
        (replace(LINE, description="  "), "line-0-description"),
        (replace(LINE, quantity_milli=0), "line-0-quantity"),
        (replace(LINE, unit_price_cents=-1), "line-0-price"),
        (replace(LINE, vat_code="VERLEGD"), "line-0-vat_code"),
        (replace(LINE, account_id=None), "line-0-account"),
        (replace(LINE, account_id=99), "line-0-account"),
    ],
)
def test_line_problems(line, field):
    assert err(lines=(line,)).field == field


def test_unsupported_vat_message_is_plain():
    e = err(lines=(replace(LINE, vat_code="EU_ICP"),))
    assert e.code == "UNSUPPORTED_VAT"
    assert "21%, 9% of 0%" in e.message


def test_zero_total_refused():
    e = err(total_incl_cents=0, lines=(replace(LINE, unit_price_cents=0),))
    assert e.message == "Het totaal is €0,00; zo'n factuur kun je niet boeken."


def test_date_order_guard():
    e = err(latest_final_date=date(2026, 3, 5))
    assert e.code == "DATE_ORDER"
    assert "01-03" not in e.message
    assert e.message == (
        "Er is al een factuur met datum 05-03-2026. Een factuur mag geen eerdere datum hebben dan de "
        "vorige, anders klopt de nummering niet. Kies 05-03-2026 of later."
    )
    check_finalizable(data(latest_final_date=date(2026, 3, 1)))  # same day is fine


def test_note_max_500():
    assert err(note="x" * 501).field == "note"
    check_finalizable(data(note="x" * 500))


def test_credit_lines_cannot_exceed_original():
    # original line 1: invoiced 3, already credited 1
    originals = {1: (3000, 1000)}
    check_credit_lines([(1, 2000)], originals)
    with pytest.raises(SalesError) as exc:
        check_credit_lines([(1, 2500)], originals)
    assert exc.value.code == "OVER_CREDIT"
    assert exc.value.message == "Je kunt maximaal 2 van deze regel crediteren; er is al 1 gecrediteerd."


def test_credit_lines_must_reference_original_line():
    with pytest.raises(SalesError) as exc:
        check_credit_lines([(None, 1000)], {1: (3000, 0)})
    assert exc.value.code == "CREDIT_LINES_FIXED"
    with pytest.raises(SalesError):
        check_credit_lines([(2, 1000)], {1: (3000, 0)})
