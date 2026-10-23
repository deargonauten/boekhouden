"""Web tests for Instellingen > Btw-codes (real migrated DB through the TestClient)."""

from datetime import date

from sqlalchemy import text

from app.web.navigation import SETTINGS_NAV

YEAR = date.today().year


def scalar(client, sql, **params):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def run(client, sql, **params):
    with client.app.state.engine.begin() as conn:
        conn.execute(text(sql), params)


def add(client, **over):
    data = {"code": "NL_6", "name": "BTW 6%", "rate": "6", "sales_rubriek": "1c", "purchase_rubriek": "5b"}
    data.update(over)
    return client.post("/instellingen/btw-codes", data=data, follow_redirects=False)


def test_nav_item_between_grootboek_and_dagboeken():
    items = SETTINGS_NAV[1].items
    assert [(i.label, i.path, i.term_key) for i in items][:3] == [
        ("Grootboek", "/instellingen/grootboek", "grootboek"),
        ("Btw-codes", "/instellingen/btw-codes", "btw_code"),
        ("Dagboeken", "/instellingen/dagboeken", "dagboek"),
    ]


def test_page_lists_all_codes_with_rubriek_labels(client):
    r = client.get("/instellingen/btw-codes")
    assert r.status_code == 200
    html = r.text
    for code in ("GEEN", "NL_21", "NL_9", "NL_0", "VERLEGD", "EU_GOEDEREN", "EU_DIENSTEN", "EXPORT"):
        assert code in html
    assert "Omzet met 21% btw" in html
    assert "Voorbelasting (btw die je terugkrijgt)" in html
    assert "Telt niet mee in de aangifte" in html
    assert "Vakje bij verkoop" in html and "Vakje bij inkoop" in html
    assert "Standaard" in html
    for key in ("rubriek", "voorbelasting", "kor"):
        assert f'data-term="{key}"' in html
    assert html.index("NL_21") < html.index("NL_9") < html.index("EXPORT")


def test_add_code(client):
    r = add(client)
    assert r.status_code == 303 and r.headers["location"] == "/instellingen/btw-codes"
    assert scalar(client, "SELECT rate_bp FROM vat_code WHERE code='NL_6'") == 600
    assert scalar(client, "SELECT purchase_rubriek FROM vat_code WHERE code='NL_6'") == "5b"
    assert "BTW 6%" in client.get("/instellingen/btw-codes").text


def test_add_decimal_rate(client):
    assert add(client, code="HALF", name="Half", rate="6,5").status_code == 303
    assert scalar(client, "SELECT rate_bp FROM vat_code WHERE code='HALF'") == 650


def test_add_errors_keep_values_and_open_modal(client):
    r = add(client, code="x", name="Mijn naam")
    assert r.status_code == 400
    assert "Een btw-code bestaat uit 2 tot 12 hoofdletters" in r.text
    assert "Mijn naam" in r.text and "data-open-on-load" in r.text
    r = add(client, code="NL_21")
    assert r.status_code == 400 and "De btw-code NL_21 bestaat al" in r.text
    r = add(client, rate="abc")
    assert r.status_code == 400 and "Vul een percentage tussen 0 en 99,99 in" in r.text
    r = add(client, sales_rubriek="5b")
    assert r.status_code == 400 and "Rubriek 5b past hier niet" in r.text
    assert "Traceback" not in r.text


def test_update_code(client):
    r = client.post(
        "/instellingen/btw-codes/NL_21",
        data={"name": "Hoog tarief", "sales_rubriek": "1a", "purchase_rubriek": ""},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert scalar(client, "SELECT name FROM vat_code WHERE code='NL_21'") == "Hoog tarief"
    assert scalar(client, "SELECT purchase_rubriek FROM vat_code WHERE code='NL_21'") is None
    assert scalar(client, "SELECT rate_bp FROM vat_code WHERE code='NL_21'") == 2100


def test_update_invalid_rubriek_is_400(client):
    r = client.post(
        "/instellingen/btw-codes/NL_21",
        data={"name": "x", "sales_rubriek": "9z", "purchase_rubriek": ""},
    )
    assert r.status_code == 400 and "Rubriek 9z past hier niet" in r.text


def test_update_rubriek_in_locked_period_is_409(client):
    assert client.post("/instellingen/boekjaren", data={"year": YEAR}, follow_redirects=False).status_code == 303
    jid = scalar(client, "SELECT id FROM journal WHERE code='MEM'")
    a4200 = scalar(client, "SELECT id FROM account WHERE code='4625'")
    a1210 = scalar(client, "SELECT id FROM account WHERE code='1210'")
    r = client.post(
        "/boeken/nieuw",
        data={
            "journal_id": str(jid), "booking_date": date.today().isoformat(), "description": "t",
            "reference": "", "line_account": [str(a4200), str(a1210)], "line_debit": ["121,00", ""],
            "line_credit": ["", "121,00"], "line_vat": ["NL_21", ""], "line_description": ["", ""],
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    run(client, "UPDATE period SET status='locked'")
    r = client.post(
        "/instellingen/btw-codes/NL_21",
        data={"name": "BTW 21%", "sales_rubriek": "1c", "purchase_rubriek": "5b"},
    )
    assert r.status_code == 409
    assert "vergrendelde periode" in r.text


def test_toggle_active_and_reactivate(client):
    add(client)
    r = client.post("/instellingen/btw-codes/NL_6/actief", data={"active": "0"}, follow_redirects=False)
    assert r.status_code == 303
    assert scalar(client, "SELECT is_active FROM vat_code WHERE code='NL_6'") == 0
    assert "Inactief" in client.get("/instellingen/btw-codes").text
    client.post("/instellingen/btw-codes/NL_6/actief", data={"active": "1"}, follow_redirects=False)
    assert scalar(client, "SELECT is_active FROM vat_code WHERE code='NL_6'") == 1


def test_deactivate_default_code_is_409(client):
    r = client.post("/instellingen/btw-codes/NL_21/actief", data={"active": "0"})
    assert r.status_code == 409
    assert "Je kunt" in r.text and "standaard btw-tarief van rekening" in r.text


def test_deactivate_geen_is_400(client):
    r = client.post("/instellingen/btw-codes/GEEN/actief", data={"active": "0"})
    assert r.status_code == 400 and "Geen btw" in r.text


def test_unknown_code_update_is_400(client):
    r = client.post("/instellingen/btw-codes/NOPE", data={"name": "x"})
    assert r.status_code == 400 and "bestaat niet" in r.text


def test_rubriek_suggestion_fragment(client):
    r = client.get("/instellingen/btw-codes/voorstel", params={"rate": "9"})
    assert r.status_code == 200
    assert 'value="1b" selected' in r.text and 'value="5b" selected' in r.text
    r = client.get("/instellingen/btw-codes/voorstel", params={"rate": "0"})
    assert 'value="1e" selected' in r.text
    # unparseable rate falls back to the 21% suggestion without an error page
    assert client.get("/instellingen/btw-codes/voorstel", params={"rate": "zz"}).status_code == 200


def test_page_is_plain_language(client):
    from tests.web_helpers import assert_plain_language

    assert_plain_language(client, "/instellingen/btw-codes")
