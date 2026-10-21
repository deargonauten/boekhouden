"""Exact plain-Dutch messages required by the spec (item 18)."""

from datetime import date

import pytest
from sqlalchemy import select

from app.domain.errors import LedgerError
from app.domain.ledger import (
    NewEntry,
    NewLine,
    add_account,
    add_journal,
    close_fiscal_year,
    create_fiscal_year,
    delete_account,
    lock_period,
    post_entry,
    rename_account,
    reverse_entry,
    validate_entry,
)
from app.domain.money import parse_euro
from app.models import Account, Period


def err(fn, *a, **kw) -> LedgerError:
    with pytest.raises(LedgerError) as exc:
        fn(*a, **kw)
    return exc.value


def entry(lines, description="x", day=date(2025, 3, 10)):
    return NewEntry(journal_id=1, booking_date=day, description=description, lines=lines)


def test_unbalanced_credit_short():
    e = err(validate_entry, entry([NewLine(1, debit_cents=10000), NewLine(2, credit_cents=8790)]))
    assert e.code == "UNBALANCED"
    assert "Debet en credit zijn niet gelijk: er ontbreekt € 12,10 aan de creditkant." in e.message
    assert "Pas een bedrag aan of voeg een regel toe." in e.message
    assert "(debet € 100,00, credit € 87,90)" in e.message


def test_unbalanced_debit_short():
    e = err(validate_entry, entry([NewLine(1, debit_cents=100), NewLine(2, credit_cents=250)]))
    assert "er ontbreekt € 1,50 aan de debetkant" in e.message


def test_too_few_lines():
    e = err(validate_entry, entry([NewLine(1, debit_cents=5)]))
    assert e.message == "Een boeking heeft minimaal twee regels nodig: één voor debet en één voor credit."


def test_invalid_line_amount():
    e = err(validate_entry, entry([NewLine(1), NewLine(2, credit_cents=5)]))
    assert e.message == (
        "Regel 1: vul bij debet óf bij credit een bedrag groter dan nul in, niet allebei en niet leeg."
    )


def test_description_and_date_messages():
    e = err(validate_entry, entry([], description=" "))
    assert e.message == "Vul een omschrijving in, bijvoorbeeld 'Kantoorbenodigdheden'."
    e = err(validate_entry, entry([], description="x" * 256))
    assert e.message == "De omschrijving is te lang (maximaal 255 tekens)."
    e = err(validate_entry, entry([], day="morgen"))
    assert e.message == "Vul een geldige datum in, bijvoorbeeld 31-12-2026."


def test_invalid_amount_message():
    e = err(parse_euro, " abc ")
    assert e.message == (
        "'abc' is geen geldig bedrag. Schrijf bijvoorbeeld 1.234,56 of 12,50 "
        "(maximaal twee cijfers achter de komma)."
    )


def test_period_messages(session, acc, jrn):
    lines = [NewLine(acc("1210"), debit_cents=5), NewLine(acc("8000"), credit_cents=5)]
    new = NewEntry(jrn("MEM"), date(2025, 3, 10), "x", lines)
    assert err(post_entry, session, new).message == (
        "Er is geen boekjaar voor 10-03-2025. Maak eerst het boekjaar aan onder Instellingen > Boekjaren."
    )
    fy = create_fiscal_year(session, 2025)
    march = session.scalar(select(Period).where(Period.fiscal_year_id == fy.id, Period.number == 3))
    lock_period(session, march.id)
    assert err(post_entry, session, new).message == (
        "De periode van 10-03-2025 is vergrendeld, dus je kunt er niet meer in boeken. "
        "Kies een datum in een open periode."
    )
    assert err(lock_period, session, 999999).code == "PERIOD_NOT_FOUND"


def test_year_messages(session):
    create_fiscal_year(session, 2025)
    assert err(create_fiscal_year, session, 2025).message == "Boekjaar 2025 bestaat al. Kies een ander jaar."
    assert err(close_fiscal_year, session, 2031).message == (
        "Boekjaar 2031 bestaat niet. Maak het eerst aan onder Instellingen > Boekjaren."
    )


def test_account_messages(session, acc):
    assert err(add_account, session, code="12", name="x", type="asset").message == (
        "Een rekeningnummer bestaat uit precies 4 cijfers, bijvoorbeeld 4010."
    )
    assert err(add_account, session, code="4971", name=" ", type="expense").message == "Geef de rekening een naam."
    assert err(add_account, session, code="4971", name="x", type="zzz").message == (
        "Kies een soort rekening uit de lijst."
    )
    assert err(add_account, session, code="1210", name="x", type="asset").message == (
        "Rekeningnummer 1210 bestaat al. Kies een ander nummer."
    )
    assert err(add_account, session, code="4971", name="x", type="expense", default_vat_code="XX").message == (
        "Deze btw-code is onbekend of niet meer in gebruik. Kies een andere uit de lijst."
    )
    sysmsg = (
        "Dit is een standaardrekening die het programma zelf nodig heeft; "
        "je kunt hem niet wijzigen of verwijderen."
    )
    assert err(rename_account, session, acc("1210"), "Nieuw").message == sysmsg
    assert err(delete_account, session, acc("1210")).message == sysmsg
    assert err(rename_account, session, 999999, "x").message == (
        "Deze rekening bestaat niet meer. Kies een andere rekening."
    )


def test_account_in_use_message(session, acc, jrn, year2025):
    custom = add_account(session, code="4971", name="Eigen", type="expense")
    lines = [NewLine(acc("1210"), debit_cents=5), NewLine(custom.id, credit_cents=5)]
    post_entry(session, NewEntry(jrn("MEM"), date(2025, 3, 10), "x", lines))
    assert err(delete_account, session, custom.id).message == (
        "Rekening 4971 wordt al gebruikt in boekingen en kan niet worden verwijderd. "
        "Zet de rekening uit; dan verschijnt hij niet meer bij nieuwe boekingen."
    )


def test_not_postable_and_inactive_messages(session, acc, jrn, year2025):
    header = add_account(session, code="4972", name="Kop", type="expense", is_postable=False)
    inactive = add_account(session, code="4973", name="Uit", type="expense")
    inactive.is_active = False
    session.flush()
    for acct, text in (
        (header, "Op rekening 4972 Kop kun je niet boeken, want het is een kopregel. Kies een rekening eronder."),
        (
            inactive,
            "Rekening 4973 Uit is uitgezet. Kies een andere rekening of zet deze rekening weer aan "
            "onder Instellingen > Grootboek.",
        ),
    ):
        lines = [NewLine(acc("1210"), debit_cents=5), NewLine(acct.id, credit_cents=5)]
        assert err(post_entry, session, NewEntry(jrn("MEM"), date(2025, 3, 10), "x", lines)).message == text
    lines = [NewLine(acc("1210"), debit_cents=5), NewLine(999999, credit_cents=5)]
    assert err(post_entry, session, NewEntry(jrn("MEM"), date(2025, 3, 10), "x", lines)).message == (
        "Deze rekening bestaat niet meer. Kies een andere rekening."
    )


def test_vat_code_message(session, acc, jrn, year2025):
    lines = [NewLine(acc("1210"), debit_cents=5), NewLine(acc("8000"), credit_cents=5, vat_code="NOPE")]
    assert err(post_entry, session, NewEntry(jrn("MEM"), date(2025, 3, 10), "x", lines)).message == (
        "Deze btw-code is onbekend of niet meer in gebruik. Kies een andere uit de lijst."
    )


def test_journal_messages(session):
    assert err(add_journal, session, code="bad", name="x", type="bank").message == (
        "Een dagboekcode bestaat uit 1 tot 6 hoofdletters of cijfers, bijvoorbeeld BANK1."
    )
    assert err(add_journal, session, code="NEW", name="", type="bank").message == "Geef het dagboek een naam."
    assert err(add_journal, session, code="NEW", name="x", type="zzz").message == (
        "Kies een soort dagboek uit de lijst."
    )
    assert err(add_journal, session, code="NEW", name="x", type="bank").message == (
        "Bij een bank- of kasdagboek hoort een rekening. Kies de rekening van je bank of kas."
    )
    assert err(add_journal, session, code="MEM", name="x", type="memoriaal").message == (
        "Dagboekcode MEM bestaat al. Kies een andere code."
    )


def test_storno_messages(session, make_entry, year2025):
    e1 = make_entry()
    storno = reverse_entry(session, e1.id)
    assert err(reverse_entry, session, e1.id).message == (
        f"Boeking {e1.entry_number} is al ongedaan gemaakt met stornoboeking {storno.entry_number}."
    )
    assert err(reverse_entry, session, storno.id).message == (
        "Een stornoboeking kun je niet nog eens ongedaan maken. Maak in plaats daarvan een nieuwe boeking."
    )
    assert err(reverse_entry, session, 999999).code == "ENTRY_NOT_FOUND"
