from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.domain.sales import (
    LineInput,
    SalesError,
    create_credit_concept,
    create_reminder,
    draft_reminder,
    eligible,
    finalize,
    get_detail,
    next_level,
    reminder_text,
)
from app.models import SalesReminder

TODAY = date(2026, 6, 30)


@pytest.fixture
def late(make_final, customer):
    # due 2026-05-01 + 30 days = 05-31, so late on TODAY
    return make_final(customer, day=date(2026, 5, 1), lines=[LineInput("Werk", 1000, 10000, "NL_21", None)])


def test_next_level():
    assert [next_level([]), next_level([1]), next_level([1, 2]), next_level([1, 2, 3]), next_level([3, 3])] == [1, 2, 3, 3, 3]


def test_text_names_all_facts_and_escalates():
    kw = dict(customer_name="Klant BV", invoice_number="2026-0007", invoice_date=date(2026, 5, 1),
              due_date=date(2026, 5, 31), open_cents=12100, new_due_date=date(2026, 7, 14),
              iban="NL91ABNA0417164300", seller_name="Jansen Webdesign")
    texts = [reminder_text(level, **kw) for level in (1, 2, 3)]
    for t in texts:
        for fact in ("Klant BV", "2026-0007", "01-05-2026", "31-05-2026", "€ 121,00", "14-07-2026", "NL91ABNA0417164300", "Jansen Webdesign"):
            assert fact in t
    assert "Misschien is het aan je aandacht ontsnapt" in texts[0]
    assert "Op onze eerdere herinnering" in texts[1]
    assert "laatste aanmaning" in texts[2]
    assert reminder_text(7, **kw) == texts[2]  # further ones repeat level 3


def test_draft_proposes_level_dates_and_mailto(session, late, customer):
    customer.email = "klant@example.nl"
    session.commit()
    draft = draft_reminder(session, late.id, TODAY)
    assert (draft.level, draft.title) == (1, "Betalingsherinnering")
    assert draft.reminder_date == TODAY and draft.new_due_date == date(2026, 7, 14)
    assert draft.open_cents == 12100 and draft.contact_email == "klant@example.nl"
    assert draft.mailto_subject == "Betalingsherinnering factuur 2026-0001"
    assert "2026-0001" in draft.body_text


def test_create_reminder_is_stored_with_pdf_and_levels_progress(session, late, storage):
    first = create_reminder(session, late.id, today=TODAY, storage=storage)
    session.commit()
    assert first.level == 1 and first.open_cents == 12100
    assert storage.exists(first.pdf_sha256, "pdf") and storage.open(first.pdf_sha256, "pdf").read().startswith(b"%PDF")
    second = create_reminder(session, late.id, today=TODAY, new_due_date=date(2026, 7, 20), storage=storage)
    session.commit()
    assert (second.level, second.new_due_date) == (2, date(2026, 7, 20))
    detail = get_detail(session, late.id, TODAY)
    assert [r.level for r in detail.reminders] == [1, 2]
    # no money moved, nothing frozen changed
    assert detail.open_cents == 12100


def test_new_due_date_must_follow_reminder_date(session, late, storage):
    with pytest.raises(SalesError):
        create_reminder(session, late.id, today=TODAY, new_due_date=TODAY, storage=storage)


def test_not_allowed_cases_have_plain_messages(session, make_final, make_concept, customer, late, storage):
    not_due = make_final(customer, day=date(2026, 6, 20), lines=[LineInput("x", 1000, 100, "NL_0", None)])
    with pytest.raises(SalesError) as exc:
        draft_reminder(session, not_due.id, TODAY)
    assert exc.value.message == "Deze factuur is nog niet te laat."
    late.paid_cents = late.total_incl_cents
    session.commit()
    with pytest.raises(SalesError) as exc:
        draft_reminder(session, late.id, TODAY)
    assert exc.value.message == "Deze factuur is al betaald."
    with pytest.raises(SalesError):
        draft_reminder(session, make_concept(customer).id, TODAY)
    note = create_credit_concept(session, not_due.id, today=TODAY)
    finalize(session, note.id, storage=storage)
    with pytest.raises(SalesError):
        draft_reminder(session, note.id, TODAY)


def test_eligible():
    assert eligible(kind="invoice", status="te_laat")
    assert not eligible(kind="invoice", status="openstaand")
    assert not eligible(kind="credit_note", status="te_laat")


def test_reminders_are_append_only(session, late, storage):
    reminder = create_reminder(session, late.id, today=TODAY, storage=storage)
    session.commit()
    with pytest.raises(DBAPIError):
        session.execute(text("UPDATE sales_reminder SET level = 2"))
    session.rollback()
    with pytest.raises(DBAPIError):
        session.execute(text("DELETE FROM sales_reminder"))
    session.rollback()
    assert session.get(SalesReminder, reminder.id) is not None
