"""Web tests for the ledger UI. Need the real ledger service (Parts A-C) and migration 0002."""

import re
from datetime import date

import pytest
from sqlalchemy import text

TODAY = date.today()
YEAR = TODAY.year


def scalar(client, sql, **params):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def account_id(client, code):
    return scalar(client, "SELECT id FROM account WHERE code = :c", c=code)


def journal_id(client, code):
    return scalar(client, "SELECT id FROM journal WHERE code = :c", c=code)


@pytest.fixture
def year_client(client):
    r = client.post("/instellingen/boekjaren", data={"year": YEAR}, follow_redirects=False)
    assert r.status_code == 303
    return client


def entry_form(client, **over):
    data = {
        "journal_id": str(journal_id(client, "MEM")),
        "booking_date": TODAY.isoformat(),
        "description": "Testboeking",
        "reference": "",
        "line_account": [str(account_id(client, "4200")), str(account_id(client, "1210"))],
        "line_debit": ["1.234,56", ""],
        "line_credit": ["", "1.234,56"],
        "line_vat": ["", ""],
        "line_description": ["", ""],
    }
    data.update(over)
    return data


def post_entry(client, **over):
    return client.post("/boeken/nieuw", data=entry_form(client, **over), follow_redirects=False)


def test_entries_empty(client):
    r = client.get("/boeken")
    assert r.status_code == 200
    assert "<h1>Boeken</h1>" in r.text
    assert "Nieuwe boeking" in r.text
    assert "Deze pagina is nog in ontwikkeling." not in r.text
    assert r.text.count('aria-current="page"') == 1


def test_new_form_renders(client):
    r = client.get("/boeken/nieuw")
    assert r.status_code == 200
    assert r.text.count('name="line_account"') == 2
    assert "Regel toevoegen" in r.text
    assert TODAY.isoformat() in r.text


def test_add_line_partial(client):
    r = client.get("/boeken/nieuw/regel")
    assert r.status_code == 200
    assert r.text.count('name="line_account"') == 1
    assert "<html" not in r.text


def test_create_entry_happy_path(year_client):
    r = post_entry(year_client)
    assert r.status_code == 303
    detail = year_client.get(r.headers["location"])
    assert detail.status_code == 200
    assert "€ 1.234,56" in detail.text
    assert "MEM-" in detail.text
    assert "Stornoboeking maken" in detail.text
    listing = year_client.get("/boeken")
    assert "Testboeking" in listing.text
    assert "€ 1.234,56" in listing.text


def test_unbalanced_entry_422_preserves_input(year_client):
    r = post_entry(year_client, line_credit=["", "1.234,55"], description="Scheef")
    assert r.status_code == 422
    assert "evenwicht" in r.text.lower()
    assert "Scheef" in r.text
    assert "1.234,56" in r.text
    assert 'alert' in r.text
    assert scalar(year_client, "SELECT count(*) FROM journal_entry") == 0


def test_bad_amount_422(year_client):
    r = post_entry(year_client, line_debit=["abc", ""])
    assert r.status_code == 422
    assert "Regel 1" in r.text


def test_missing_year_is_409(client):
    r = post_entry(client)
    assert r.status_code == 409
    assert "boekjaar" in r.text.lower()


def test_storno_flow(year_client):
    loc = post_entry(year_client).headers["location"]
    entry_id = int(loc.rsplit("/", 1)[1])
    r = year_client.post(f"/boeken/{entry_id}/storno", data={"datum": ""}, follow_redirects=False)
    assert r.status_code == 303
    storno = year_client.get(r.headers["location"])
    assert "Storno van" in storno.text
    assert "Stornoboeking maken" not in storno.text
    original = year_client.get(loc)
    assert "Gestorneerd door" in original.text
    assert "Stornoboeking maken" not in original.text
    listing = year_client.get("/boeken").text
    assert "Gestorneerd" in listing
    assert "Storno van" in listing
    again = year_client.post(f"/boeken/{entry_id}/storno", data={"datum": ""})
    assert again.status_code == 409


def test_locked_period_blocks_posting(year_client):
    period_id = scalar(
        year_client,
        "SELECT p.id FROM period p JOIN fiscal_year f ON f.id = p.fiscal_year_id "
        "WHERE f.year = :y AND p.number = :n",
        y=YEAR, n=TODAY.month,
    )
    r = year_client.post(
        f"/instellingen/boekjaren/periodes/{period_id}/vergrendel", follow_redirects=False
    )
    assert r.status_code == 303
    r = post_entry(year_client)
    assert r.status_code == 409
    assert "vergrendeld" in r.text.lower()
    assert scalar(year_client, "SELECT count(*) FROM journal_entry") == 0


def test_unknown_entry_404(client):
    assert client.get("/boeken/9999").status_code == 404
    assert client.post("/boeken/9999/storno").status_code == 404


def test_journal_filter(year_client):
    post_entry(year_client)
    assert "Testboeking" in year_client.get("/boeken?dagboek=MEM").text
    assert "Testboeking" not in year_client.get("/boeken?dagboek=VK").text


def test_instellingen_redirect_and_nav(client):
    r = client.get("/instellingen", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/instellingen/grootboek"
    for path in ("grootboek", "dagboeken", "boekjaren"):
        html = client.get(f"/instellingen/{path}").text
        active = re.findall(r'<a [^>]*class="nav-link active[^"]*"[^>]*>\s*(.*?)\s*</a>', html, re.S)
        assert active == ["Instellingen"]


def test_accounts_page_and_add(client):
    html = client.get("/instellingen/grootboek").text
    assert "Debiteuren" in html
    r = client.post(
        "/instellingen/grootboek",
        data={"code": "4777", "name": "Eigen rekening", "type": "expense"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Eigen rekening" in client.get("/instellingen/grootboek").text
    dup = client.post(
        "/instellingen/grootboek",
        data={"code": "4777", "name": "Dubbel", "type": "expense"},
    )
    assert dup.status_code in (409, 422)
    assert 'role="alert"' in dup.text


def test_account_toggle(client):
    aid = account_id(client, "4960")
    r = client.post(
        f"/instellingen/grootboek/{aid}/actief", data={"active": "0"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert scalar(client, "SELECT is_active FROM account WHERE id = :i", i=aid) == 0


def test_journals_page_and_add(client):
    html = client.get("/instellingen/dagboeken").text
    assert "Memoriaal" in html
    r = client.post(
        "/instellingen/dagboeken",
        data={"code": "BANK2", "name": "Tweede bank", "type": "bank",
              "account_id": str(account_id(client, "1220"))},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "Tweede bank" in client.get("/instellingen/dagboeken").text


def test_fiscal_years_page(client):
    html = client.get("/instellingen/boekjaren").text
    assert "Boekjaar aanmaken" in html
    assert "Er is nog geen boekjaar" in html
    client.post("/instellingen/boekjaren", data={"year": YEAR})
    html = client.get("/instellingen/boekjaren").text
    assert f"Boekjaar {YEAR}" in html
    assert html.count("Vergrendel periode") == 12
    assert "hx-confirm" in html
    dup = client.post("/instellingen/boekjaren", data={"year": YEAR})
    assert dup.status_code == 409
    assert 'role="alert"' in dup.text


def test_base_swaps_409_422_responses(client):
    # hx-boost drops 4xx by default; base.html must opt in so error messages show
    html = client.get("/instellingen/boekjaren").text
    assert "htmx:beforeSwap" in html
    assert "409" in html and "422" in html


def test_close_year(year_client):
    r = year_client.post(f"/instellingen/boekjaren/{YEAR}/afsluiten", follow_redirects=False)
    assert r.status_code == 303
    assert "Afgesloten" in year_client.get("/instellingen/boekjaren").text
    assert post_entry(year_client).status_code == 409


def test_no_database_file_touched(client, test_settings):
    client.get("/boeken")
    assert "test.db" in test_settings.database_url
