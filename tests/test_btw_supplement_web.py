"""Web tests for suppleties: stand per vandaag, suppletie maken/verwijderen, meenemen in een latere aangifte."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ledger import NewEntry, NewLine, post_entry
from app.domain.vat import VatPeriod, file_vat_return
from app.models import Journal
from tests.vat.vat_helpers import Book, set_company
from tests.web_helpers import assert_plain_language

YEAR = date.today().year
Q1 = f"/btw/{YEAR}/quarter/1"
Q2 = f"/btw/{YEAR}/quarter/2"


@pytest.fixture
def filed(client):
    """Q1 filed with a sale; then an expense booked into the locked Q1 (with explicit consent)."""
    with Session(client.app.state.engine) as s:
        book = Book(s, YEAR)
        set_company(s)
        book.sale(100_000, 21_000, day=date(YEAR, 2, 10))
        book.sale(50_000, 10_500, day=date(YEAR, 5, 10))
        file_vat_return(s, VatPeriod(YEAR, "quarter", 1), filed_on=date.today(), today=date.today())
        jid = s.scalar(select(Journal.id).where(Journal.code == "IK"))
        lines = [NewLine(book.acc("4000"), debit_cents=10_000, vat_code="NL_21"),
                 NewLine(book.acc("1400"), debit_cents=2_100), NewLine(book.acc("2000"), credit_cents=12_100)]
        post_entry(s, NewEntry(jid, date(YEAR, 3, 5), "Late inkoop", lines), allow_locked_period=True)
        s.commit()
    return client


def test_overview_and_page_flag_the_difference(filed):
    assert "Wijkt af" in filed.get(f"/btw?jaar={YEAR}").text
    page = filed.get(Q1 + "?tab=stand").text
    assert "wijkt af van de stand per vandaag" in page and "Suppletie maken" in page
    assert_plain_language(filed, Q1 + "?tab=stand")
    assert_plain_language(filed, Q2)


def test_create_view_and_delete_supplement(filed):
    r = filed.post(Q1 + "/suppletie", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("?tab=suppletie")
    page = filed.get(Q1 + "?tab=suppletie").text
    assert "Verwijderen" in page and "volgende btw-aangifte" in page
    assert filed.post(Q1 + "/suppletie").status_code == 409  # one open suppletie per period
    sid = page.split("/suppletie/")[1].split("/")[0]
    r = filed.post(f"{Q1}/suppletie/{sid}/verwijderen", follow_redirects=False)
    assert r.status_code == 303
    assert "Suppletie maken" in filed.get(Q1 + "?tab=stand").text


def test_take_supplement_along_in_next_return(filed):
    filed.post(Q1 + "/suppletie")
    page = filed.get(Q2).text
    assert "Welke suppleties wil je meenemen" in page and "Suppletie over" in page and "checked" in page
    unchecked = filed.get(Q2 + "?gekozen=1").text
    assert "checked" not in unchecked.split("Welke suppleties")[1].split("</form>")[0]
    confirm = filed.get(Q2 + "/indienen?suppletie=1").text
    assert 'name="suppletie" value="1"' in confirm
    r = filed.post(Q2 + "/indienen", data={"filed_on": date.today().isoformat(), "suppletie": "1"}, follow_redirects=False)
    assert r.status_code == 303
    done = filed.get(Q2).text
    assert "suppleties meegenomen" in done
    stand = filed.get(Q1 + "?tab=suppletie").text
    assert "Meegenomen in" in stand and "Verwijderen" not in stand
    sid = 1
    assert filed.post(f"{Q1}/suppletie/{sid}/verwijderen").status_code == 409
    assert "wijkt af" not in filed.get(Q1 + "?tab=stand").text


def test_unknown_supplement_is_404(filed):
    assert filed.post(f"{Q1}/suppletie/999/verwijderen").status_code == 404
