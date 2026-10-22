"""Web tests for grootboek-verfijning Part 5: grootboek columns and btw suggestion on /boeken/nieuw."""

import re

from sqlalchemy import text


def scalar(client, sql, **params):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def aid(client, code):
    return scalar(client, "SELECT id FROM account WHERE code = :c", c=code)


def test_grootboek_has_new_columns_and_terms(client):
    html = client.get("/instellingen/grootboek").text
    assert 'data-term="standaard_btw"' in html
    assert 'data-term="selecteerbaar_bij"' in html
    a = aid(client, "4210")
    assert f'action="/instellingen/grootboek/{a}/btw"' in html
    assert f'action="/instellingen/grootboek/{a}/selecteerbaar"' in html
    assert "Geen suggestie" in html


def test_grootboek_hidden_system_account_is_read_only(client):
    html = client.get("/instellingen/grootboek").text
    a = aid(client, "1300")
    assert f'action="/instellingen/grootboek/{a}/selecteerbaar"' not in html
    assert "standaardrekening die het programma zelf gebruikt" in html


def test_set_btw_default_persists_and_clears(client):
    a = aid(client, "4210")
    r = client.post(f"/instellingen/grootboek/{a}/btw", data={"vat_code": "NL_9"}, follow_redirects=False)
    assert r.status_code == 303
    assert scalar(client, "SELECT default_vat_code FROM account WHERE id=:i", i=a) == "NL_9"
    client.post(f"/instellingen/grootboek/{a}/btw", data={"vat_code": ""})
    assert scalar(client, "SELECT default_vat_code FROM account WHERE id=:i", i=a) is None


def test_set_btw_default_unknown_code_shows_dutch_error(client):
    a = aid(client, "4210")
    r = client.post(f"/instellingen/grootboek/{a}/btw", data={"vat_code": "NOPE"})
    assert r.status_code == 422
    assert 'role="alert"' in r.text
    assert "btw-code" in r.text.lower()
    assert "Traceback" not in r.text


def test_set_selecteerbaar_persists(client):
    a = aid(client, "4210")
    r = client.post(f"/instellingen/grootboek/{a}/selecteerbaar", data={"sales": "1"}, follow_redirects=False)
    assert r.status_code == 303

    def row(col):
        return scalar(client, f"SELECT {col} FROM account WHERE id=:i", i=a)

    assert (row("selectable_purchase"), row("selectable_sales"), row("selectable_bank")) == (0, 1, 0)


def test_selecteerbaar_system_account_refused(client):
    a = aid(client, "1300")
    r = client.post(f"/instellingen/grootboek/{a}/selecteerbaar", data={"purchase": "1"})
    assert r.status_code == 409
    assert "standaardrekening die het programma zelf gebruikt" in r.text


def test_unknown_account_gives_error_not_exception(client):
    r = client.post("/instellingen/grootboek/999999/btw", data={"vat_code": ""})
    assert r.status_code == 404
    assert "bestaat niet meer" in r.text


def test_add_account_with_defaults_and_contexts(client):
    html = client.get("/instellingen/grootboek").text
    assert 'name="default_vat_code"' in html
    assert 'name="purchase"' in html and "Dit zijn voorstellen" in html
    r = client.post(
        "/instellingen/grootboek",
        data={"code": "4777", "name": "Eigen", "type": "expense", "default_vat_code": "NL_21",
              "purchase": "1", "bank": "1"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    a = aid(client, "4777")
    assert scalar(client, "SELECT default_vat_code FROM account WHERE id=:i", i=a) == "NL_21"
    assert scalar(client, "SELECT selectable_purchase FROM account WHERE id=:i", i=a) == 1
    assert scalar(client, "SELECT selectable_sales FROM account WHERE id=:i", i=a) == 0


def test_entry_form_options_carry_data_vat(client):
    html = client.get("/boeken/nieuw").text
    assert '<script src="/static/js/vat-suggest.js"' in html
    m = re.search(r'<option value="%d"[^>]*>' % aid(client, "4210"), html)
    assert m and 'data-vat="NL_21"' in m.group(0)
    m = re.search(r'<option value="%d"[^>]*>' % aid(client, "1210"), html)
    assert m and 'data-vat=""' in m.group(0)
    # still lists every postable account, e.g. a bank account
    assert f'<option value="{aid(client, "1210")}"' in html


def test_data_vat_omits_inactive_code(client):
    a = aid(client, "4210")
    client.post(f"/instellingen/grootboek/{a}/btw", data={"vat_code": "NL_9"})
    with client.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE vat_code SET is_active=0 WHERE code='NL_9'"))
    html = client.get("/boeken/nieuw").text
    m = re.search(r'<option value="%d"[^>]*>' % a, html)
    assert 'data-vat=""' in m.group(0)


def test_line_row_fragment_has_data_vat(client):
    html = client.get("/boeken/nieuw/regel").text
    assert 'data-vat="NL_21"' in html


def test_script_served(client):
    r = client.get("/static/js/vat-suggest.js")
    assert r.status_code == 200
    assert "touched" in r.text
