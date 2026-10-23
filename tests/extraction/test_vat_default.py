"""The account's standaard btw-tarief fills a line when the extraction gave no usable code."""

from datetime import date

from app.domain.extraction import service
from app.domain.extraction.suggestions import resolve_vat_code_for_account
from app.domain.extraction.types import ExtractedInvoice, ExtractedLine
from app.domain.relations import ExtractedContact

RATES = {"NL_21": 2100, "NL_9": 900, "GEEN": 0}


def test_returns_the_accounts_default_when_active():
    assert resolve_vat_code_for_account("4635", {"4635": "NL_21"}, RATES) == "NL_21"


def test_none_without_account_or_default():
    assert resolve_vat_code_for_account(None, {"4635": "NL_21"}, RATES) is None
    assert resolve_vat_code_for_account("4635", {"4635": None}, RATES) is None
    assert resolve_vat_code_for_account("9999", {}, RATES) is None


def test_none_when_default_code_is_inactive():
    assert resolve_vat_code_for_account("4635", {"4635": "KOR"}, RATES) is None


def inv(line: ExtractedLine) -> ExtractedInvoice:
    return ExtractedInvoice(
        supplier=ExtractedContact(name="Bol B.V.", kvk="12345678"),
        invoice_number="F-1",
        invoice_date=date.today(),
        total_excl_cents=10000,
        total_vat_cents=None,
        total_incl_cents=None,
        lines=(line,),
        raw="{}",
    )


def test_store_result_prefills_default_vat_when_no_code_resolvable(session, make_doc):
    line = ExtractedLine("Abonnement", 10000, None, None, "4635")
    ex = service.store_result(session, make_doc().id, "fake", None, inv(line))
    (stored,) = ex.lines
    assert stored.vat_code == "NL_21"


def test_store_result_keeps_given_code(session, make_doc):
    line = ExtractedLine("Abonnement", 10000, "NL_9", 900, "4635")
    (stored,) = service.store_result(session, make_doc().id, "fake", None, inv(line)).lines
    assert stored.vat_code == "NL_9"


def test_store_result_keeps_code_inferred_from_amounts(session, make_doc):
    line = ExtractedLine("Boeken", 10000, None, 900, "4635")
    (stored,) = service.store_result(session, make_doc().id, "fake", None, inv(line)).lines
    assert stored.vat_code == "NL_9"


def test_store_result_without_account_has_no_vat_code(session, make_doc):
    line = ExtractedLine("Iets", 10000, None, None, None)
    (stored,) = service.store_result(session, make_doc().id, "fake", None, inv(line)).lines
    assert stored.vat_code is None
