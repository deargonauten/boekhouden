"""Web tests for /instellingen/beginbalans. Domain rules are tested in tests/opening."""

import re

from sqlalchemy import text

from tests.web_helpers import assert_plain_language

URL = "/instellingen/beginbalans"
START = "2025-01-01"


def scalar(client, sql, **params):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def account_id(client, code):
    return scalar(client, "SELECT id FROM account WHERE code = :c", c=code)


def make_contact(client, name, role="is_supplier"):
    r = client.post("/relaties/nieuw", data={"name": name, role: "1"}, follow_redirects=False)
    assert r.status_code == 303
    return int(r.headers["location"].rsplit("=", 1)[1])


def start_year(client, year=2025):
    assert client.post("/instellingen/boekjaren", data={"year": year}).status_code in (200, 303)


def form(client, balances=None, items=None):
    """Form data. balances: {code: text}; items: [(side, contact_id, number, date, due, amount)]."""
    balances = balances or {}
    items = items or []
    data = {
        "balance_account": [str(account_id(client, c)) for c in balances],
        "balance_amount": list(balances.values()),
        "item_side": [i[0] for i in items],
        "item_contact": [str(i[1]) for i in items],
        "item_number": [i[2] for i in items],
        "item_date": [i[3] for i in items],
        "item_due": [i[4] for i in items],
        "item_amount": [i[5] for i in items],
    }
    return data


def book(client, balances=None, items=None):
    return client.post(URL, data=form(client, balances, items), follow_redirects=False)


def test_without_boekjaar_shows_plain_message_and_link(client):
    r = client.get(URL)
    assert r.status_code == 200
    assert "Maak eerst je eerste boekjaar aan onder Instellingen &gt; Boekjaren." in r.text
    assert 'href="/instellingen/boekjaren"' in r.text
    assert "Beginbalans boeken" not in r.text


def test_page_renders_cards_and_info_icons(client):
    start_year(client)
    r = client.get(URL)
    assert r.status_code == 200
    html = r.text
    assert "Waarmee begin je? (beginbalans)" in html
    assert "Wat heb je?" in html and "Wat moet je nog betalen?" in html and "Openstaande facturen" in html
    assert "Klanten die jou nog moeten betalen" in html and "Leveranciers die jij nog moet betalen" in html
    assert "Beginbalans boeken" in html
    assert "01-01-2025" in html
    assert 'data-term="beginbalans"' in html and 'data-term="openstaande_post"' in html
    # 1300/3000/equity are derived, not typed
    assert "1300 Debiteuren" not in html and "3000 Crediteuren" not in html
    assert "1210" in html  # a bank account is offered


def test_settings_nav_has_beginbalans_tab(client):
    start_year(client)
    html = client.get("/instellingen/grootboek").text
    assert 'href="/instellingen/beginbalans"' in html


def test_add_row_partial(client):
    start_year(client)
    make_contact(client, "Bol B.V.")
    r = client.get(f"{URL}/regel?side=crediteur")
    assert r.status_code == 200
    assert 'name="item_side" value="crediteur"' in r.text
    assert "Bol B.V." in r.text
    assert 'name="item_number"' in r.text
    d = client.get(f"{URL}/regel?side=debiteur")
    assert 'value="debiteur"' in d.text


def test_controle_summary_is_computed_on_the_server(client):
    start_year(client)
    r = client.post(f"{URL}/controle", data=form(client, {"1210": "1.000,00", "3150": "300,00"}))
    assert r.status_code == 200
    assert "€ 1.000,00" in r.text and "€ 300,00" in r.text and "€ 700,00" in r.text
    assert "Eigen vermogen (berekend)" in r.text


def test_controle_negative_equity_warns_and_ignores_bad_input(client):
    start_year(client)
    r = client.post(f"{URL}/controle", data=form(client, {"1210": "abc", "3150": "300,00"}))
    assert r.status_code == 200
    assert "Je schulden zijn hoger dan je bezittingen" in r.text


def test_post_books_and_redirects_with_notice(client):
    start_year(client)
    supplier = make_contact(client, "Bol B.V.")
    r = book(client, {"1210": "1.000,00"}, [("crediteur", supplier, "F-1", "2024-12-01", "2024-12-31", "121,00")])
    assert r.status_code == 303
    assert r.headers["location"].startswith(f"{URL}?melding=geboekt")
    page = client.get(r.headers["location"])
    assert "De beginbalans is geboekt." in page.text
    m = re.search(r'href="/boeken/(\d+)"', page.text)
    assert m
    entry = client.get(f"/boeken/{m.group(1)}")
    assert "Bekijk beginbalans" in entry.text
    assert scalar(client, "SELECT kind FROM journal_entry WHERE source_type='beginbalans'") == "opening"
    assert scalar(client, "SELECT count(*) FROM opening_item") == 1
    # the booked page shows item status and the aanpassen button
    assert "Beginbalans aanpassen en opnieuw boeken" in page.text
    assert "Open" in page.text and "Beginbalans boeken" not in page.text.replace("Beginbalans aanpassen en opnieuw boeken", "")
    assert "maken de oude boeking ongedaan" in page.text


def test_empty_form_is_refused_in_plain_dutch(client):
    start_year(client)
    r = book(client)
    assert r.status_code == 422
    assert "Vul minstens één bedrag of openstaande factuur in." in r.text
    assert 'role="alert"' in r.text


def test_invalid_amount_keeps_values(client):
    start_year(client)
    r = book(client, {"1210": "12x", "3150": "300,00"})
    assert r.status_code == 422
    assert "Vul bij 1210" in r.text and "een geldig bedrag in, bijvoorbeeld 1.250,00." in r.text
    assert 'value="12x"' in r.text and 'value="300,00"' in r.text
    assert scalar(client, "SELECT count(*) FROM journal_entry WHERE source_type='beginbalans'") == 0


def test_domain_error_422_keeps_rows(client):
    start_year(client)
    supplier = make_contact(client, "Bol B.V.")
    r = book(client, {"1210": "100,00"}, [("crediteur", supplier, "F-1", "2025-03-01", "", "50,00")])
    assert r.status_code == 422
    assert "De factuurdatum ligt na de startdatum van je administratie." in r.text
    assert "Openstaande factuur 1 (leveranciers)" in r.text
    assert 'value="F-1"' in r.text and 'value="2025-03-01"' in r.text and "selected" in r.text


def test_fully_empty_rows_are_dropped(client):
    start_year(client)
    r = book(client, {"1210": "100,00"}, [("debiteur", "", "", "", "", ""), ("crediteur", "", "", "", "", "")])
    assert r.status_code == 303


def test_aanpassen_flow_and_unchanged_notice(client):
    start_year(client)
    supplier = make_contact(client, "Bol B.V.")
    items = [("crediteur", supplier, "F-1", "2024-12-01", "", "121,00")]
    assert book(client, {"1210": "1.000,00"}, items).status_code == 303
    same = book(client, {"1210": "1.000,00"}, items)
    assert same.status_code == 200
    assert "Er is niets veranderd." in same.text
    assert 'role="alert"' not in same.text
    prefilled = client.get(URL).text
    assert 'value="1000,00"' in prefilled and 'value="F-1"' in prefilled
    r = book(client, {"1210": "2.000,00"}, items)
    assert r.status_code == 303
    assert scalar(client, "SELECT count(*) FROM journal_entry WHERE source_type='beginbalans'") == 2
    page = client.get(URL).text
    assert "Open" in page


def test_locked_first_period_is_read_only(client):
    start_year(client)
    assert book(client, {"1210": "1.000,00"}).status_code == 303
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE period SET status='locked' WHERE number=1"))
    page = client.get(URL).text
    assert "Je eerste periode is vergrendeld; de beginbalans kan niet meer worden aangepast." in page
    assert "<fieldset disabled" in page
    assert "Beginbalans aanpassen en opnieuw boeken" not in page
    r = book(client, {"1210": "2.000,00"})
    assert r.status_code == 422
    assert scalar(client, "SELECT count(*) FROM journal_entry WHERE source_type='beginbalans'") == 1


def test_inkoop_shows_opening_block(client):
    start_year(client)
    supplier = make_contact(client, "Bol B.V.")
    book(client, {}, [("crediteur", supplier, "F-9", "2024-11-01", "2024-11-30", "121,00")])
    html = client.get("/inkoop").text
    assert "Nog te betalen uit je beginbalans" in html
    assert "F-9" in html and "Te laat" in html and "€ 121,00" in html
    assert "waarvan 1 uit beginbalans" in html


def test_inkoop_without_opening_items_has_no_block(client):
    start_year(client)
    assert "Nog te betalen uit je beginbalans" not in client.get("/inkoop").text


def test_page_is_plain_language(client):
    start_year(client)
    supplier = make_contact(client, "Bol B.V.")
    assert_plain_language(client, URL)
    book(client, {"1210": "100,00"}, [("crediteur", supplier, "F-1", "2024-12-01", "", "10,00")])
    assert_plain_language(client, URL)
    assert_plain_language(client, "/inkoop")


def test_account_rows_lead_with_plain_dutch_and_have_explainers(client):
    start_year(client)
    html = client.get(URL).text
    # A plain label first, then the grootboek name, then the info marker whose
    # explainer lives in the glossary.
    from app.domain.glossary import GLOSSARY
    from app.web.opening_routes import ACCOUNT_TERM

    for code, key in ACCOUNT_TERM.items():
        row = re.search(rf"<td><strong>[^<]*</strong> <span class=\"hint\">{code} .*?</td>", html, re.S)
        assert row, f"geen uitleg-rij voor {code}"
        cell = row.group(0)
        assert f'data-term="{key}"' in cell, f"{code}: geen uitleg ({key})"
        assert cell.index(GLOSSARY[key].plain) < cell.index(code), f"{code}: gewone taal komt niet eerst"
    for plain in ("Al afgeschreven waarde", "Geld dat nog onderweg is", "Btw-saldo met de Belastingdienst"):
        assert plain in html
