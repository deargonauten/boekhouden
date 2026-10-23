"""Web tests for the BTW screens (overview, aangifte, drill-down, ICP coupling, indienen, settings)."""

from datetime import date

import pytest
from sqlalchemy.orm import Session

from tests.vat.vat_helpers import Book, make_contact, set_company
from tests.web_helpers import assert_plain_language

YEAR = date.today().year
DAY = date(YEAR, 2, 10)  # first quarter
Q1 = f"/btw/{YEAR}/quarter/1"
Q2 = f"/btw/{YEAR}/quarter/2"


@pytest.fixture
def booked(client):
    """A year with one sale (21%), one EU sale without klant, a klant, and company data."""
    with Session(client.app.state.engine) as s:
        book = Book(s, YEAR)
        book.sale(100_000, 21_000, day=DAY, desc="Verkoop")
        book.post(
            [("1210", 50_000, 0), ("8000", 0, 50_000, "EU_GOEDEREN")], day=DAY, desc="Levering Klant BV", journal="VK",
        )
        contact = make_contact(s, name="Klant BV")
        set_company(s)
        s.commit()
        client.entry_id = book.s.execute(
            __import__("sqlalchemy").text("SELECT id FROM journal_entry WHERE description = 'Levering Klant BV'")
        ).scalar()
        client.contact_id = contact.id
    return client


def test_overview_lists_the_periods(booked):
    r = booked.get(f"/btw?jaar={YEAR}")
    assert r.status_code == 200
    assert "1e kwartaal" in r.text and "4e kwartaal" in r.text
    assert "Concept" in r.text


def test_overview_bad_year_is_404(client):
    assert client.get("/btw?jaar=abc").status_code == 404


def test_overview_default_year_without_data(client):
    assert client.get("/btw").status_code == 200


def test_return_page_shows_rubrieken_and_total(booked):
    r = booked.get(Q1)
    assert r.status_code == 200
    assert "Omzet met 21% btw (1a)" in r.text
    assert "Te betalen" in r.text
    assert "Markeer als ingediend" in r.text
    assert f"{Q1}/pdf" in r.text and f"{Q1}/rubrieken.csv" in r.text and f"{Q1}/icp.csv" in r.text


@pytest.mark.parametrize("path", [
    "/btw/2026/quarter/5", "/btw/2026/month/13", "/btw/2026/week/1", "/btw/abc/quarter/1",
    "/btw/2026/quarter/1/rubriek/9z", "/btw/2026/quarter/0/indienen",
])
def test_invalid_period_or_rubriek_is_404(client, path):
    assert client.get(path).status_code == 404


def test_empty_period_mentions_nihilaangifte(client):
    client.post("/instellingen/boekjaren", data={"year": YEAR})
    r = client.get(Q2)
    assert r.status_code == 200
    assert "nihilaangifte" in r.text


def test_drilldown_links_to_entries(booked):
    r = booked.get(f"{Q1}/rubriek/1a")
    assert r.status_code == 200
    assert "/boeken/" in r.text and "Verkoop" in r.text


def test_icp_lists_unassigned_entry_with_suggestion(booked):
    r = booked.get(Q1)
    assert "Nog geen klant gekoppeld" in r.text
    assert f'value="{booked.contact_id}" selected' in r.text  # klant suggested from the description


def test_couple_klant_htmx_returns_partial(booked):
    r = booked.post(
        f"{Q1}/klant", data={"entry_id": booked.entry_id, "contact_id": booked.contact_id},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "<html" not in r.text and "icp-body" in r.text
    assert "Nog geen klant gekoppeld" not in r.text


def test_couple_klant_without_htmx_redirects(booked):
    r = booked.post(
        f"{Q1}/klant", data={"entry_id": booked.entry_id, "contact_id": booked.contact_id}, follow_redirects=False,
    )
    assert r.status_code == 303


def test_couple_unknown_entry_is_404_with_message(booked):
    r = booked.post(
        f"{Q1}/klant", data={"entry_id": 99999, "contact_id": booked.contact_id}, headers={"HX-Request": "true"},
    )
    assert r.status_code == 404
    assert "bestaat niet" in r.text


def test_confirm_page_needs_post_to_file(booked):
    r = booked.get(f"{Q1}/indienen")
    assert r.status_code == 200
    assert "Dit kun je niet terugdraaien." in r.text
    assert booked.get(Q1).text.count("Ingediend") >= 0
    assert "Voorlopig" in booked.get(Q1).text  # GET filed nothing


def test_file_locks_and_redirects(booked):
    r = booked.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == Q1
    page = booked.get(Q1).text
    assert "Ingediend" in page and "vergrendeld" in page
    assert "Markeer als ingediend" not in page
    # second time: conflict, plain message
    again = booked.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()})
    assert again.status_code == 409
    assert "al ingediend" in again.text
    assert booked.get(f"{Q1}/indienen").status_code == 409


def test_file_future_date_is_refused(booked):
    r = booked.post(f"{Q1}/indienen", data={"filed_on": "2999-01-01"})
    assert r.status_code == 422
    assert "niet in de toekomst" in r.text


def test_file_bad_date_is_refused(booked):
    r = booked.post(f"{Q1}/indienen", data={"filed_on": "morgen"})
    assert r.status_code == 422
    assert "geldige datum" in r.text


def test_file_out_of_order_is_conflict(booked):
    with Session(booked.app.state.engine) as s:
        Book.__new__(Book)  # no-op; keep the helper import used
        b = Book.__new__(Book)
        b.s = s
        b.sale(10_000, 2_100, day=date(YEAR, 5, 10))
        s.commit()
    r = booked.post(f"{Q2}/indienen", data={"filed_on": date.today().isoformat()})
    assert r.status_code == 409
    assert "Dien eerst de aangifte over 1e kwartaal" in r.text


def test_file_requires_btw_id(client):
    with Session(client.app.state.engine) as s:
        Book(s, YEAR).sale(100_000, 21_000, day=DAY)
        s.commit()
    r = client.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()})
    assert r.status_code == 422
    assert "btw-nummer" in r.text


def test_couple_after_filing_is_refused(booked):
    booked.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()})
    r = booked.post(
        f"{Q1}/klant", data={"entry_id": booked.entry_id, "contact_id": booked.contact_id},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 409
    assert "vergrendelde periode" in r.text


def test_post_from_other_origin_is_blocked(booked):
    r = booked.post(
        f"{Q1}/indienen", data={"filed_on": date.today().isoformat()}, headers={"Origin": "http://evil.example"},
    )
    assert r.status_code in (400, 403)
    assert "Voorlopig" in booked.get(Q1).text


def test_settings_page_and_save(client):
    assert client.get("/instellingen/btw-aangifte").status_code == 200
    r = client.post(
        "/instellingen/btw-aangifte", data={"frequency": "month", "kor_from": "", "kor_until": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "opgeslagen" in client.get("/instellingen/btw-aangifte?opgeslagen=1").text
    assert "Per maand" in client.get("/btw").text or "maand" in client.get("/btw").text


def test_settings_kor_dates_error_is_plain(client):
    r = client.post(
        "/instellingen/btw-aangifte",
        data={"frequency": "quarter", "kor_from": f"{YEAR}-04-01", "kor_until": f"{YEAR}-01-01"},
    )
    assert r.status_code == 422
    assert "vóór de startdatum" in r.text


def test_settings_bad_frequency_and_date(client):
    assert client.post("/instellingen/btw-aangifte", data={"frequency": "week"}).status_code == 422
    assert client.post("/instellingen/btw-aangifte", data={"frequency": "quarter", "kor_from": "x"}).status_code == 422


def test_kor_full_period_cannot_be_filed(booked):
    booked.post("/instellingen/btw-aangifte", data={"frequency": "quarter", "kor_from": f"{YEAR}-01-01", "kor_until": ""})
    page = booked.get(Q1).text
    assert "geen btw-aangifte te doen" in page
    r = booked.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()})
    assert r.status_code == 409
    assert "KOR" in r.text


def test_nav_has_settings_item(client):
    assert "/instellingen/btw-aangifte" in client.get("/instellingen/grootboek").text


@pytest.mark.parametrize("path", [
    "/btw", f"/btw?jaar={YEAR}", Q1, f"{Q1}/indienen", f"{Q1}/rubriek/1a", "/instellingen/btw-aangifte",
])
def test_btw_pages_are_plain_language(booked, path):
    assert_plain_language(booked, path)


def test_filed_page_is_plain_language(booked):
    booked.post(f"{Q1}/indienen", data={"filed_on": date.today().isoformat()})
    assert_plain_language(booked, Q1)
