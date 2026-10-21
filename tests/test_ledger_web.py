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
    # sidebar item + the active "Alle" tab
    assert r.text.count('aria-current="page"') == 2
    assert "Je hebt nog geen boekingen" in r.text


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
    assert "Debet en credit zijn niet gelijk" in r.text
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
    assert html.count("Periode vergrendelen") == 12
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


# --- Boeken list: search, pager, empty states (ui-redesign part 2) -----------


@pytest.fixture
def small_pages(monkeypatch):
    from app.web import ledger_routes

    monkeypatch.setattr(ledger_routes, "PER_PAGE", 2)


def test_search_matches_number_description_reference_case_insensitive(year_client):
    post_entry(year_client, description="Kantoorspullen", reference="FACT-77")
    post_entry(year_client, description="Huur")
    html = year_client.get("/boeken?q=KANTOOR").text
    assert "Kantoorspullen" in html and "Huur" not in html
    assert "Kantoorspullen" in year_client.get("/boeken?q=fact-77").text
    assert "Huur" in year_client.get("/boeken?q=mem-").text


def test_search_percent_and_underscore_are_literal(year_client):
    post_entry(year_client, description="Korting 10% extra")
    post_entry(year_client, description="Korting 10 procent")
    html = year_client.get("/boeken?q=10%25").text
    assert "Korting 10% extra" in html and "10 procent" not in html
    assert "Geen boekingen gevonden" in year_client.get("/boeken?q=_").text


def test_search_combines_with_journal(year_client):
    post_entry(year_client, description="Zoekterm")
    assert "Zoekterm" in year_client.get("/boeken?dagboek=MEM&q=zoek").text
    assert "Geen boekingen gevonden" in year_client.get("/boeken?dagboek=VK&q=zoek").text


def test_no_match_empty_state_offers_to_clear_filters(year_client):
    post_entry(year_client)
    html = year_client.get("/boeken?q=bestaatniet").text
    assert "Geen boekingen gevonden" in html
    assert "Wis filters" in html and 'href="/boeken"' in html
    assert "Je hebt nog geen boekingen" not in html


def test_pager_shows_count_and_keeps_params(year_client, small_pages):
    for n in range(5):
        post_entry(year_client, description=f"Zoek {n}")
    post_entry(year_client, description="Anders")
    html = year_client.get("/boeken?q=zoek&dagboek=MEM").text
    assert "Toont 1-2 van 5 boekingen" in html
    assert "q=zoek" in html and "dagboek=MEM" in html and "page=2" in html
    assert 'aria-label="Paginering"' in html
    assert "Toont 5-5 van 5 boekingen" in year_client.get("/boeken?q=zoek&page=3").text


def test_page_is_clamped(year_client, small_pages):
    for n in range(3):
        post_entry(year_client, description=f"Boeking {n}")
    for bad in ("0", "-4"):
        assert "Toont 1-2 van 3 boekingen" in year_client.get(f"/boeken?page={bad}").text
    assert "Toont 3-3 van 3 boekingen" in year_client.get("/boeken?page=999").text


def test_single_page_shows_count_only(year_client):
    post_entry(year_client)
    html = year_client.get("/boeken").text
    assert "Toont 1-1 van 1 boekingen" in html
    assert "Volgende" not in html


def test_storno_pills_in_list(year_client):
    r = post_entry(year_client)
    year_client.post(r.headers["location"] + "/storno", data={"datum": ""})
    html = year_client.get("/boeken").text
    assert "Gestorneerd" in html and "Storno van" in html
    assert "pill--warning" in html and "pill--neutral" in html


def test_dagboek_tabs_for_few_journals(client):
    html = client.get("/boeken?dagboek=MEM").text
    assert 'class="tabs"' in html
    assert html.count('aria-current="page"') == 2


def test_settings_tabs_mark_current(client):
    for path in ("grootboek", "dagboeken", "boekjaren"):
        html = client.get(f"/instellingen/{path}").text
        assert 'class="tabs"' in html
        assert re.search(rf'<a href="/instellingen/{path}" aria-current="page"', html)
        assert html.count('aria-current="page"') == 2


def test_year_periods_use_pills(year_client):
    html = year_client.get("/instellingen/boekjaren").text
    assert "pill--success" in html
    pid = scalar(year_client, "SELECT id FROM period ORDER BY id LIMIT 1")
    year_client.post(f"/instellingen/boekjaren/periodes/{pid}/vergrendel")
    html = year_client.get("/instellingen/boekjaren").text
    assert "Vergrendeld" in html and "pill--neutral" in html
    assert html.count("Periode vergrendelen") == 11


def test_system_accounts_show_pill(client):
    html = client.get("/instellingen/grootboek").text
    assert "Systeem" in html and 'data-filter-table' in html


def test_new_entry_form_uses_cards_and_fields(client):
    html = client.get("/boeken/nieuw").text
    assert html.count('class="card') >= 2
    assert 'class="field' in html
    assert "form-actions" in html


def test_ledger_css_is_served_and_uses_tokens_only(client):
    r = client.get("/static/css/ledger.css")
    assert r.status_code == 200
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", r.text)
    assert "/static/css/ledger.css" in client.get("/boeken").text
