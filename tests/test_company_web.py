"""Web tests for /instellingen/bedrijfsgegevens. Validation rules: tests/domain/test_company_validation.py."""

import re

URL = "/instellingen/bedrijfsgegevens"
FULL = {
    "legal_name": "Jan de Vries", "legal_form": "eenmanszaak", "address_line": "Dorpsstraat 1",
    "postal_code": "1234ab", "city": "Utrecht", "country": "NL", "kvk": "12345678",
    "btw_id": "NL123456789B01", "iban": "NL91ABNA0417164300",
}


def test_empty_form_suggests_defaults(client):
    r = client.get(URL)
    assert r.status_code == 200
    html = r.text
    assert 'name="country" value="NL"' in html
    assert re.search(r'<option value="eenmanszaak"[^>]*\sselected', html)
    assert "Dit zijn de gegevens van jouw bedrijf." in html
    assert 'name="legal_name" value=""' in html


def test_completeness_notice_lists_missing_items(client):
    html = client.get(URL).text
    assert "Voor het maken van facturen ontbreekt nog:" in html
    client.post(URL, data={"legal_name": "Jan", "postal_code": "", "city": "Utrecht",
                           "kvk": "12345678", "btw_id": "NL123456789B01", "iban": "NL91ABNA0417164300"})
    html = client.get(URL).text
    assert "ontbreekt nog: adres, postcode." in html


def test_complete_profile_says_so(client):
    client.post(URL, data=FULL)
    html = client.get(URL).text
    assert "Je bedrijfsgegevens zijn compleet voor facturen." in html
    assert "ontbreekt nog" not in html


def test_valid_post_redirects_and_flashes(client):
    r = client.post(URL, data=FULL, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == f"{URL}?opgeslagen=1"
    html = client.get(r.headers["location"]).text
    assert "Bedrijfsgegevens opgeslagen." in html
    assert 'value="Jan de Vries"' in html
    assert 'value="1234 AB"' in html
    assert 'value="NL91 ABNA 0417 1643 00"' in html
    assert "Bedrijfsgegevens opgeslagen." not in client.get(URL).text


def test_resave_updates_the_single_row(client):
    client.post(URL, data=FULL)
    client.post(URL, data={**FULL, "city": "Amersfoort"})
    assert 'value="Amersfoort"' in client.get(URL).text
    with client.app.state.engine.connect() as conn:
        from sqlalchemy import text
        assert conn.execute(text("SELECT count(*) FROM company_profile")).scalar() == 1


def test_only_name_is_needed_to_save(client):
    r = client.post(URL, data={"legal_name": "Jan"}, follow_redirects=False)
    assert r.status_code == 303


def test_invalid_post_keeps_typed_values_and_lists_all_messages(client):
    bad = {**FULL, "kvk": "123", "btw_id": "DE123456789", "iban": "NL91ABNA0417164301",
           "postal_code": "12", "city": "Zeist"}
    r = client.post(URL, data=bad)
    assert r.status_code == 422
    html = r.text
    assert 'role="alert"' in html
    assert "Je KvK-nummer bestaat uit 8 cijfers" in html
    assert "Je btw-id ziet eruit als NL123456789B01" in html
    assert "Dit IBAN klopt niet" in html
    assert "Een Nederlandse postcode bestaat uit 4 cijfers en 2 letters" in html
    assert 'value="123"' in html and 'value="DE123456789"' in html and 'value="Zeist"' in html
    assert 'value="NL91ABNA0417164301"' in html
    assert "Traceback" not in html


def test_invalid_post_saves_nothing(client):
    client.post(URL, data={**FULL, "kvk": "123"})
    html = client.get(URL).text
    assert 'name="legal_name" value=""' in html


def test_missing_name_message(client):
    r = client.post(URL, data={**FULL, "legal_name": ""})
    assert r.status_code == 422
    assert "Vul de naam van je bedrijf of je eigen naam in." in r.text


def test_settings_nav_shows_bedrijfsgegevens_active(client):
    html = client.get(URL).text
    nav = re.search(r'<nav class="settings-nav".*?</nav>', html, re.S).group(0)
    assert 'settings-nav__heading">Mijn bedrijf<' in nav
    assert nav.index("Mijn bedrijf") < nav.index("Boekhouding")
    assert re.search(r'href="/instellingen/bedrijfsgegevens" aria-current="page">Bedrijfsgegevens', nav)
    assert nav.count('aria-current="page"') == 1


def test_instellingen_still_redirects_to_grootboek(client):
    r = client.get("/instellingen", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    assert r.headers["location"] == "/instellingen/grootboek"


def test_labels_and_terms_in_plain_dutch(client):
    html = client.get(URL).text
    for label in ("Naam van je bedrijf of je eigen naam", "Handelsnaam (als die anders is)",
                  "Inschrijfnummer Kamer van Koophandel", "Btw-identificatienummer", "Bankrekeningnummer"):
        assert label in html
    for key in ("bedrijfsgegevens", "handelsnaam", "rechtsvorm", "kvk", "btw_id", "iban"):
        assert f'data-term="{key}"' in html
    assert "Staat op je btw-aangifte en op brieven van de Belastingdienst" in html
