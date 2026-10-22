"""Beginbalans service: booking, aanpassen (storno + new), read model, refusals."""

from datetime import date

import pytest
from sqlalchemy import func, select, text

from app.domain.errors import LedgerError
from app.domain.ledger import (
    create_fiscal_year,
    lock_period,
    post_entry,
    set_account_active,
    set_journal_active,
    trial_balance,
)
from app.domain.ledger.entries import NewEntry, NewLine
from app.domain.opening import (
    OpeningError,
    OpeningInput,
    OpeningItemInput,
    allowed_accounts,
    book_opening_balance,
    first_fiscal_year,
    first_period_locked,
    get_opening_balance,
    list_opening_items,
    preview,
)
from app.domain.opening import service as opening_service
from app.models import Account, Contact, JournalEntry, JournalLine, OpeningItem, Period

START = date(2025, 1, 1)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def deb(contact, number="V-1", amount=12100, day=date(2024, 12, 1), due=None):
    return OpeningItemInput("debiteur", contact.id, number, day, due, amount)


def cred(contact, number="I-1", amount=5000, day=date(2024, 12, 5), due=None):
    return OpeningItemInput("crediteur", contact.id, number, day, due, amount)


@pytest.fixture
def people(make_contact):
    return dict(
        jansen=make_contact("Jansen", customer=True),
        bol=make_contact("Bol B.V.", supplier=True),
    )


@pytest.fixture
def basic(acc, people):
    """Bank 10.000, auto 8.000, afschrijving -2.000, lening 6.000, one post each side."""
    return OpeningInput(
        balances=[(acc("1210"), 1000000), (acc("0120"), 800000), (acc("0190"), -200000), (acc("3600"), 600000)],
        items=[deb(people["jansen"]), cred(people["bol"])],
    )


def book(session, data, **kw):
    entry = book_opening_balance(session, data, **kw)
    session.commit()
    return entry


def lines_of(session, entry_id):
    rows = session.execute(
        select(JournalLine, Account.code)
        .join(Account, Account.id == JournalLine.account_id)
        .where(JournalLine.entry_id == entry_id)
        .order_by(JournalLine.line_no)
    ).all()
    return [(code, l.debit_cents, l.credit_cents, l.vat_code) for l, code in rows]


# --- accounts / years --------------------------------------------------------------------
def test_allowed_accounts(session, acc):
    set_account_active(session, acc("1220"), False)
    refs = allowed_accounts(session)
    codes = [r.code for r in refs]
    assert {"1210", "0120", "0190", "1400", "3150", "3600"} <= set(codes)
    assert not {"1300", "3000", "2000", "2900", "1220", "8000", "4200"} & set(codes)
    assert refs == sorted(refs, key=lambda r: (r.type, r.code))  # assets first, then by code


def test_first_fiscal_year_is_earliest(session):
    assert first_fiscal_year(session) is None
    create_fiscal_year(session, 2026)
    create_fiscal_year(session, 2025)
    assert first_fiscal_year(session).year == 2025


# --- happy path --------------------------------------------------------------------------
def test_book_happy_path(session, year2025, basic, people, jrn):
    entry = book(session, basic)
    assert entry.kind == "opening"
    assert entry.journal_id == jrn("MEM")
    assert entry.booking_date == START
    assert entry.description == "Beginbalans 2025"
    assert entry.reference is None
    assert entry.entry_number == "MEM-2025-0001"
    assert (entry.source_type, entry.source_id) == ("beginbalans", year2025.id)
    assert lines_of(session, entry.id) == [
        ("0120", 800000, 0, None),
        ("0190", 0, 200000, None),
        ("1210", 1000000, 0, None),
        ("3600", 0, 600000, None),
        ("1300", 12100, 0, None),
        ("3000", 0, 5000, None),
        ("2000", 0, 1007100, None),
    ]
    items = list(session.scalars(select(OpeningItem).order_by(OpeningItem.id)))
    assert [(i.side, i.contact_id, i.invoice_number, i.invoice_number_key, i.amount_cents, i.paid_cents) for i in items] == [
        ("debiteur", people["jansen"].id, "V-1", "v-1", 12100, 0),
        ("crediteur", people["bol"].id, "I-1", "i-1", 5000, 0),
    ]
    assert all(i.journal_entry_id == entry.id and i.fiscal_year_id == year2025.id for i in items)


def test_trial_balance(session, year2025, basic):
    book(session, basic)
    rows = {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session, up_to=START)}
    assert rows == {
        "0120": 800000,
        "0190": -200000,
        "1210": 1000000,
        "1300": 12100,
        "2000": -1007100,
        "3000": -5000,
        "3600": -600000,
    }
    tb = trial_balance(session, up_to=START)
    assert sum(r.debit_cents for r in tb) == sum(r.credit_cents for r in tb)


def test_contact_flags_are_set(session, year2025, make_contact):
    supplier_only = make_contact("Alleen leverancier", supplier=True)
    customer_only = make_contact("Alleen klant", customer=True)
    book(session, OpeningInput([], [deb(supplier_only), cred(customer_only)]))
    session.refresh(supplier_only)
    session.refresh(customer_only)
    assert supplier_only.is_customer and supplier_only.is_supplier
    assert customer_only.is_customer and customer_only.is_supplier


def test_items_only_and_negative_equity(session, year2025, people):
    entry = book(session, OpeningInput([], [cred(people["bol"], amount=7000)]))
    assert lines_of(session, entry.id) == [("3000", 0, 7000, None), ("2000", 7000, 0, None)]


# --- read model --------------------------------------------------------------------------
def test_get_opening_balance(session, year2025, basic, people):
    assert get_opening_balance(session) is None
    entry = book(session, basic)
    view = get_opening_balance(session, today=date(2025, 1, 15))
    assert view.fiscal_year_id == year2025.id and view.year == 2025 and view.start_date == START
    assert (view.entry_id, view.entry_number) == (entry.id, "MEM-2025-0001")
    assert [(b.code, b.amount_cents) for b in view.balances] == [
        ("0120", 800000), ("0190", -200000), ("1210", 1000000), ("3600", 600000)
    ]
    assert view.balances[0].name == "Bedrijfsauto" and view.balances[3].type == "liability"
    assert [(i.side, i.relation_name, i.invoice_number, i.amount_cents, i.open_cents, i.status) for i in view.items] == [
        ("debiteur", "Jansen", "V-1", 12100, 12100, "open"),
        ("crediteur", "Bol B.V.", "I-1", 5000, 5000, "open"),
    ]
    assert view.assets_cents == 1600000 + 12100
    assert view.liabilities_cents == 605000
    assert view.equity_cents == 1007100
    assert view.period_locked is False
    # prefill: the view converts back to the same input
    assert sorted(view.to_input().balances) == sorted(basic.balances)


def test_preview(session, year2025, acc, people):
    s = preview(
        session,
        OpeningInput(
            [(acc("1210"), 1000), (acc("3600"), 5000), (acc("2000"), 999), (acc("1210"), 1.5)],
            [deb(people["jansen"], amount=500), OpeningItemInput("crediteur", None, "", None, None, 0)],
        ),
    )
    assert (s.assets_cents, s.liabilities_cents, s.equity_cents) == (1500, 5000, -3500)
    assert len(s.warnings) == 1 and "negatief" in s.warnings[0]


def test_preview_without_fiscal_year(session, acc):
    s = preview(session, OpeningInput([(acc("1210"), 1000)], []))
    assert s.equity_cents == 1000


# --- refusals ----------------------------------------------------------------------------
def refused(session, data, code, **kw):
    with pytest.raises(LedgerError) as exc:
        book_opening_balance(session, data, **kw)
    session.rollback()
    assert exc.value.code == code
    return exc.value


def test_no_fiscal_year(session, acc):
    err = refused(session, OpeningInput([(acc("1210"), 100)], []), "NO_FISCAL_YEAR")
    assert isinstance(err, OpeningError)
    assert err.message == "Maak eerst je eerste boekjaar aan onder Instellingen > Boekjaren."


def test_not_first_year(session, year2025, acc):
    create_fiscal_year(session, 2026)
    session.commit()
    err = refused(session, OpeningInput([(acc("1210"), 100)], []), "NOT_FIRST_YEAR", year=2026)
    assert err.message == (
        "De beginbalans van 2026 volgt uit het boekjaar ervoor. "
        "Alleen je eerste boekjaar (2025) krijgt een beginbalans."
    )
    assert book(session, OpeningInput([(acc("1210"), 100)], []), year=2025).booking_date == START


def test_no_memoriaal(session, year2025, acc, jrn):
    set_journal_active(session, jrn("MEM"), False)
    session.commit()
    err = refused(session, OpeningInput([(acc("1210"), 100)], []), "NO_JOURNAL")
    assert err.message == "Er is geen memoriaal actief. Zet het memoriaal aan onder Instellingen > Dagboeken."


def test_account_not_allowed_names_account(session, year2025, acc):
    err = refused(session, OpeningInput([(acc("1300"), 100)], []), "ACCOUNT_NOT_ALLOWED")
    assert err.message.startswith("Rekening 1300 Debiteuren hoort niet in de beginbalans.")


def test_empty(session, year2025):
    refused(session, OpeningInput([], []), "EMPTY")


def test_unknown_or_archived_contact(session, year2025, people):
    from app.domain.relations.service import set_contact_active

    ghost = Contact(id=999)
    err = refused(session, OpeningInput([], [deb(ghost)]), "INVALID_ITEM")
    assert err.message.startswith("Openstaande factuur 1 (klanten): ")
    set_contact_active(session, people["bol"].id, False)
    session.commit()
    err = refused(session, OpeningInput([], [cred(people["bol"])]), "INVALID_ITEM")
    assert err.message.startswith("Openstaande factuur 1 (leveranciers): ")
    assert "gearchiveerd" in err.message


def test_duplicate_names_relation(session, year2025, people):
    err = refused(session, OpeningInput([], [deb(people["jansen"]), deb(people["jansen"], " v-1")]), "DUPLICATE_ITEM")
    assert err.message == "Factuur v-1 van Jansen staat er twee keer in."


def test_locked_first_period_persists_nothing(session, year2025, basic, make_entry):
    p1 = session.scalar(select(Period).where(Period.fiscal_year_id == year2025.id, Period.number == 1))
    lock_period(session, p1.id)
    session.commit()
    refused(session, basic, "PERIOD_LOCKED")
    assert count(session, JournalEntry) == 0 and count(session, OpeningItem) == 0
    assert first_period_locked(session) is True
    # sequence not consumed
    assert make_entry().entry_number == "MEM-2025-0001"


# --- aanpassen ---------------------------------------------------------------------------
def test_aanpassen_is_storno_plus_new_entry(session, year2025, basic, acc, people):
    old = book(session, basic)
    changed = OpeningInput(
        balances=[(acc("1210"), 1100000)],
        items=[cred(people["bol"], "I-2", amount=3000)],
    )
    new = book(session, changed)
    storno = session.scalar(select(JournalEntry).where(JournalEntry.reverses_entry_id == old.id))
    assert storno.kind == "storno"
    assert storno.booking_date == START
    assert storno.description == "Storno beginbalans 2025 (aangepast)"
    assert new.id != old.id and new.kind == "opening"
    assert (new.source_type, new.source_id) == ("beginbalans", year2025.id)
    assert new.entry_number == "MEM-2025-0003"

    view = get_opening_balance(session)
    assert view.entry_id == new.id
    assert [(b.code, b.amount_cents) for b in view.balances] == [("1210", 1100000)]
    assert [i.invoice_number for i in view.items] == ["I-2"]

    all_cred = list_opening_items(session, "crediteur", open_only=False)
    assert [(i.invoice_number, i.status, i.open_cents) for i in all_cred] == [
        ("I-1", "vervangen", 0),
        ("I-2", "open", 3000),
    ]
    assert [i.invoice_number for i in list_opening_items(session, "crediteur")] == ["I-2"]
    assert list_opening_items(session, "debiteur") == []
    # only one active beginbalans; ledger shows just the new amounts
    rows = {r.code: r.debit_cents - r.credit_cents for r in trial_balance(session, up_to=START) if r.debit_cents != r.credit_cents}
    assert rows == {"1210": 1100000, "3000": -3000, "2000": -1097000}


def test_aanpassen_identical_input_is_unchanged(session, year2025, basic, people):
    book(session, basic)
    before = count(session, JournalEntry)
    reordered = OpeningInput(list(reversed(basic.balances)), [cred(people["bol"], " i-1 ".upper()), deb(people["jansen"])])
    err = refused(session, reordered, "UNCHANGED")
    assert err.message == "Er is niets veranderd."
    assert count(session, JournalEntry) == before


def test_aanpassen_refused_when_item_paid(session, year2025, basic, acc):
    book(session, basic)
    session.execute(text("UPDATE opening_item SET paid_cents = 100 WHERE invoice_number = 'V-1'"))
    session.commit()
    before = count(session, JournalEntry)
    err = refused(session, OpeningInput([(acc("1210"), 1)], []), "ITEM_PAID")
    assert err.message == (
        "Factuur V-1 uit je beginbalans is al (deels) betaald. "
        "Pas de beginbalans aan met een gewone boeking in het memoriaal."
    )
    assert count(session, JournalEntry) == before
    paid = list_opening_items(session, "debiteur", open_only=False)[0]
    assert (paid.open_cents, paid.status) == (12000, "open")


def test_aanpassen_refused_when_first_period_locked(session, year2025, basic, acc):
    book(session, basic)
    p1 = session.scalar(select(Period).where(Period.fiscal_year_id == year2025.id, Period.number == 1))
    lock_period(session, p1.id)
    session.commit()
    refused(session, OpeningInput([(acc("1210"), 1)], []), "PERIOD_LOCKED")
    assert count(session, JournalEntry) == 1 and count(session, OpeningItem) == 2
    assert get_opening_balance(session).period_locked is True


def test_failure_halfway_rolls_back_everything(session, year2025, basic, acc, people, monkeypatch):
    book(session, basic)

    def boom(*a, **kw):
        raise LedgerError("BOOM", "kapot")

    monkeypatch.setattr(opening_service, "_set_contact_flags", boom)
    with pytest.raises(LedgerError, match="kapot"):
        book_opening_balance(session, OpeningInput([(acc("1210"), 1)], [cred(people["bol"])]))
    session.commit()  # even if the caller commits, nothing of the failed attempt remains
    assert count(session, JournalEntry) == 1 and count(session, OpeningItem) == 2
    assert get_opening_balance(session).entry_number == "MEM-2025-0001"
    monkeypatch.undo()
    assert book(session, OpeningInput([(acc("1210"), 1)], [])).entry_number == "MEM-2025-0003"


def test_manual_storno_leaves_no_active_beginbalans(session, year2025, basic):
    from app.domain.ledger import reverse_entry

    entry = book(session, basic)
    reverse_entry(session, entry.id)
    session.commit()
    assert get_opening_balance(session) is None
    assert {i.status for i in list_opening_items(session, "debiteur", open_only=False)} == {"vervangen"}
    assert book(session, basic).kind == "opening"  # a fresh one, no second storno


def test_other_mem_entries_do_not_count(session, year2025, acc, jrn):
    post_entry(
        session,
        NewEntry(jrn("MEM"), START, "Handmatige opening", [NewLine(acc("1210"), 100), NewLine(acc("2000"), 0, 100)], kind="opening"),
    )
    session.commit()
    assert get_opening_balance(session) is None
