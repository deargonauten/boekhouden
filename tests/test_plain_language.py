"""Enforcement tests for the plain-language requirement (CLAUDE.md).

Add the pages of every new feature to PAGES so terms without an explainer fail here.
"""

import re
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.domain import ledger
from app.domain.glossary import GLOSSARY
from app.web import ledger_routes, opening_routes
from app.web.navigation import NAV_ITEMS
from tests.web_helpers import (
    assert_plain_language,
    bare_term_elements,
    missing_term_keys,
    visible_text,
)

TODAY = date.today()
YEAR = TODAY.year
TEMPLATES = Path(__file__).parent.parent / "app" / "web" / "templates"

# Glossary keys that no template/nav item/label table uses (max 5, each justified).
# STAGED (grootboek-verfijning part 7): these keys are used by the Part 4/5 templates.
UNUSED_OK: set[str] = set()

# STAGED: flip to True once Part 4 (/instellingen/btw-codes) is merged.
BTW_CODES_PAGE_MERGED = True


def scalar(client, sql, **params):
    with client.app.state.engine.connect() as conn:
        return conn.execute(text(sql), params).scalar()


def account_id(client, code):
    return scalar(client, "SELECT id FROM account WHERE code = :c", c=code)


def entry_data(client, **over):
    data = {
        "journal_id": str(scalar(client, "SELECT id FROM journal WHERE code = 'MEM'")),
        "booking_date": TODAY.isoformat(),
        "description": "Testboeking",
        "reference": "",
        "line_account": [str(account_id(client, "4200")), str(account_id(client, "1210"))],
        "line_debit": ["100,00", ""],
        "line_credit": ["", "100,00"],
        "line_vat": ["", ""],
        "line_description": ["", ""],
    }
    data.update(over)
    return data


@pytest.fixture
def seeded(client):
    client.post("/instellingen/boekjaren", data={"year": YEAR})
    r = client.post("/boeken/nieuw", data=entry_data(client), follow_redirects=False)
    assert r.status_code == 303
    entry_url = r.headers["location"]
    c = client.post(
        "/relaties/nieuw",
        data={"name": "Jansen Installatie", "is_supplier": "1", "kvk": "12345678"},
        follow_redirects=False,
    )
    assert c.status_code == 303
    co = client.post("/instellingen/bedrijfsgegevens", data=COMPANY, follow_redirects=False)
    assert co.status_code == 303
    client.contact_id = int(c.headers["location"].rsplit("=", 1)[1])
    entry_id = int(entry_url.rsplit("/", 1)[1])
    s = client.post(f"/boeken/{entry_id}/storno", data={"datum": ""}, follow_redirects=False)
    assert s.status_code == 303
    up = client.post(
        "/inbox/upload", files=[("files", ("factuur.pdf", b"%PDF-1.4\n%%EOF\n", "application/pdf"))]
    )
    assert up.status_code == 200
    client.entry_url = entry_url
    client.storno_url = s.headers["location"]
    return client


def pages(c):
    return [
        ("/boeken", set()),
        ("/boeken/nieuw", set()),
        (c.entry_url, set()),
        (c.storno_url, set()),
        ("/instellingen/grootboek", set()),
        ("/instellingen/dagboeken", set()),
        ("/instellingen/boekjaren", set()),
        ("/instellingen/bedrijfsgegevens", set()),  # filled (seeded)
        ("/instellingen/bedrijfsgegevens?opgeslagen=1", set()),  # filled, with flash
        ("/relaties", set()),
        ("/relaties?gearchiveerd=1", set()),
        ("/relaties?soort=klant", set()),
        ("/relaties?q=zzz", set()),
        ("/boeken?q=test", set()),
        ("/boeken?q=bestaatniet", set()),
        ("/boeken?dagboek=MEM", set()),
        ("/relaties/nieuw", set()),
        (f"/relaties/{c.contact_id}/bewerken", set()),
        ("/inkoop", set()),
        ("/inkoop?tab=all", set()),
        ("/instellingen/beginbalans", set()),
        ("/instellingen/beginbalans?melding=geboekt", set()),
        ("/bank", set()),
        ("/bank?tab=geschiedenis", set()),
        ("/bank/rekeningen/nieuw", set()),
        ("/bank/importeren", set()),
        ("/inbox", set()),
        ("/inbox?status=nieuw", set()),
        ("/inbox?status=geboekt", set()),
        ("/inbox/1", set()),
        ("/inbox/1/nakijken", set()),  # not yet read out; the ok/failed states: tests/test_extraction_web.py
        ("/btw", set()),
        (f"/btw?jaar={YEAR}", set()),
        (f"/btw/{YEAR}/quarter/1", set()),
        (f"/btw/{YEAR}/quarter/1/indienen", set()),
        (f"/btw/{YEAR}/quarter/1/rubriek/1a", set()),
        ("/instellingen/btw-aangifte", set()),
        (f"/controle/{YEAR}/quarter/1", set()),
    ] + ([("/instellingen/btw-codes", set())] if BTW_CODES_PAGE_MERGED else [])


COMPANY = {
    "legal_name": "Jan de Vries", "legal_form": "eenmanszaak", "address_line": "Dorpsstraat 1",
    "postal_code": "1234ab", "city": "Utrecht", "country": "NL", "kvk": "12345678",
    "btw_id": "NL123456789B01", "iban": "NL91ABNA0417164300",
}


def test_company_form_empty_is_plain_language(client):
    html = assert_plain_language(client, "/instellingen/bedrijfsgegevens")
    assert "Voor het maken van facturen ontbreekt nog" in html


def test_company_form_error_state_is_plain_language(client):
    r = client.post("/instellingen/bedrijfsgegevens", data={**COMPANY, "kvk": "123", "btw_id": "x"})
    assert r.status_code == 422
    assert missing_term_keys(r.text) == []
    assert bare_term_elements(r.text) == []
    assert 'role="alert"' in r.text


def test_empty_inbox_is_plain_language(client):
    assert_plain_language(client, "/inbox")


def test_inbox_upload_result_block_is_plain_language(client):
    pdf = b"%PDF-1.4\n%%EOF\n"
    files = [
        ("files", ("a.pdf", pdf, "application/pdf")),
        ("files", ("b.pdf", pdf, "application/pdf")),
        ("files", ("c.txt", b"tekst", "text/plain")),
    ]
    r = client.post("/inbox/upload", files=files)
    assert r.status_code == 200
    assert missing_term_keys(r.text) == []
    assert bare_term_elements(r.text) == []
    assert "Dit bestandstype kan niet worden verwerkt" in r.text


# --- 23a: template keys ------------------------------------------------------


def template_keys() -> set[str]:
    pattern = re.compile(r"""\b(?:info|term_label|explain)\(\s*["'](\w+)["']""")
    keys = set()
    for path in TEMPLATES.rglob("*.html"):
        keys |= set(pattern.findall(path.read_text()))
    return keys


def label_table_keys() -> set[str]:
    return (
        set(ledger_routes.ACCOUNT_TYPE_TERM.values())
        | set(ledger_routes.JOURNAL_TYPE_TERM.values())
        | set(opening_routes.ACCOUNT_TERM.values())
    )


def test_template_keys_exist_in_glossary():
    nav = {i.term_key for i in NAV_ITEMS if getattr(i, "term_key", None)}
    unknown = (template_keys() | nav | label_table_keys()) - set(GLOSSARY)
    assert not unknown, f"keys not in glossary: {sorted(unknown)}"


def test_every_glossary_key_is_used():
    assert len(UNUSED_OK) <= 5
    nav = {i.term_key for i in NAV_ITEMS if getattr(i, "term_key", None)}
    used = template_keys() | nav | label_table_keys() | UNUSED_OK
    assert not (set(GLOSSARY) - used), f"unused glossary keys: {sorted(set(GLOSSARY) - used)}"


# --- 23b/c: rendered pages ---------------------------------------------------


def test_every_term_on_every_page_has_an_info_icon_and_plain_wording(seeded):
    for url, allow in pages(seeded):
        assert_plain_language(seeded, url, allow)


def test_sidebar_items_carry_the_explanation(seeded):
    html = seeded.get("/boeken").text
    for item in NAV_ITEMS:
        key = getattr(item, "term_key", None)
        if key:
            assert GLOSSARY[key].explanation in html or f'title="{GLOSSARY[key].explanation}"' in html, key


def test_enforcement_detects_a_missing_icon_and_a_bare_term():
    html = "<h2>Grootboek</h2><p>Het dagboek.</p><table><tr><td>Debiteuren</td></tr></table>"
    assert missing_term_keys(html) == ["grootboek", "dagboek"]
    assert bare_term_elements(html) == ["Grootboek"]
    assert "Debiteuren" not in visible_text(html)
    ok = '<h2>Overzicht (Grootboek) <span data-term="grootboek"></span></h2>'
    assert missing_term_keys(ok) == [] and bare_term_elements(ok) == []


# --- 23d: plain-Dutch errors -------------------------------------------------


def test_unbalanced_entry_says_what_is_missing(seeded):
    r = seeded.post(
        "/boeken/nieuw", data=entry_data(seeded, line_credit=["", "87,90"])
    )
    assert r.status_code == 422
    assert 'role="alert"' in r.text
    assert "Debet en credit zijn niet gelijk: er ontbreekt € 12,10" in r.text


def test_invalid_date_message(seeded):
    r = seeded.post("/boeken/nieuw", data=entry_data(seeded, booking_date="morgen"))
    assert r.status_code == 422
    assert "Vul een geldige datum in" in r.text


def test_missing_dagboek_and_account_messages(seeded):
    r = seeded.post(
        "/boeken/nieuw",
        data=entry_data(seeded, journal_id="", line_account=["", ""]),
    )
    assert r.status_code == 422
    assert "Kies in welk dagboek je wilt boeken." in r.text
    assert "Regel 1: kies een rekening." in r.text


def test_line_with_both_or_no_amount_message(seeded):
    r = seeded.post("/boeken/nieuw", data=entry_data(seeded, line_credit=["50,00", "100,00"]))
    assert r.status_code == 422
    assert "Regel 1: vul een bedrag in bij debet of credit, niet allebei." in r.text


def test_unbalanced_footer_says_which_side(seeded):
    r = seeded.post("/boeken/nieuw", data=entry_data(seeded, line_credit=["", "87,90"]))
    assert "Er ontbreekt € 12,10 aan de creditkant." in r.text
    assert "Totaal debet / credit" in r.text and "Verschil" in r.text


def test_locked_period_message(seeded):
    pid = scalar(
        seeded,
        "SELECT p.id FROM period p JOIN fiscal_year f ON f.id = p.fiscal_year_id "
        "WHERE f.year = :y AND p.number = :n",
        y=YEAR, n=TODAY.month,
    )
    seeded.post(f"/instellingen/boekjaren/periodes/{pid}/vergrendel")
    r = seeded.post("/boeken/nieuw", data=entry_data(seeded))
    assert r.status_code == 409
    assert "is vergrendeld" in r.text
    assert "Kies een datum in een open periode" in r.text


def test_duplicate_account_code_message(client):
    data = {"code": "4777", "name": "Eigen", "type": "expense"}
    client.post("/instellingen/grootboek", data=data)
    r = client.post("/instellingen/grootboek", data=data)
    assert r.status_code in (409, 422)
    assert 'role="alert"' in r.text
    assert "bestaat al. Kies een ander nummer." in r.text


def test_error_text_is_not_wrapped(seeded):
    r = seeded.post("/boeken/nieuw", data=entry_data(seeded, line_credit=["", "87,90"]))
    assert "Fout:" not in r.text


# --- 25: suggested defaults --------------------------------------------------


def test_new_entry_defaults(client):
    html = client.get("/boeken/nieuw").text
    mem = scalar(client, "SELECT id FROM journal WHERE code = 'MEM'")
    assert re.search(rf'<option value="{mem}"[^>]*\sselected', html)
    assert TODAY.isoformat() in html
    first_vat = re.search(r'name="line_vat".*?<option value="">(.*?)</option>', html, re.S)
    assert first_vat.group(1).strip() == "Geen btw"
    assert "<optgroup" in html and "Kosten (wat je uitgeeft)" in html
    assert not re.search(r"<option[^>]*>NL_\d+", html)  # plain name first, code in brackets
    assert re.search(r"<option value=\"[^\"]+\">[^<]+\(NL_21\)</option>", html)


def test_grootboek_prefills_free_account_code(client):
    html = client.get("/instellingen/grootboek").text
    code = re.search(r'name="code" value="(\d{4})"', html).group(1)
    assert scalar(client, "SELECT count(*) FROM account WHERE code = :c", c=code) == 0
    assert "Voorstel: eerste vrije nummer in dit gebied." in html


def test_boekjaren_suggests_first_free_year(client):
    def suggested():
        return int(re.search(r'name="year"[^>]*value="(\d+)"', client.get("/instellingen/boekjaren").text).group(1))

    with Session(client.app.state.engine) as s:
        assert suggested() == ledger.suggest_fiscal_year(s, TODAY) == YEAR
    client.post("/instellingen/boekjaren", data={"year": YEAR})
    with Session(client.app.state.engine) as s:
        assert suggested() == ledger.suggest_fiscal_year(s, TODAY) == YEAR + 1


def test_dagboeken_use_plain_type_names(client):
    html = client.get("/instellingen/dagboeken").text
    assert "Memoriaal (overige boekingen)" in html
    assert not re.search(r"<td>\s*memoriaal\s*</td>", html)
    assert not re.search(r"<td>\s*(verkoop|inkoop|bank|kas)\s*</td>", html)


def test_dagboeken_preselect_the_bank_account(client):
    html = client.get("/instellingen/dagboeken").text
    bank = account_id(client, "1210")
    assert re.search(rf'<option value="{bank}"[^>]*\sselected', html)


def test_headings_are_followed_by_a_lead_sentence(client):
    leads = {
        "/instellingen/grootboek": "Dit is de lijst met alle rekeningen",
        "/instellingen/dagboeken": "Een dagboek is een map",
        "/instellingen/boekjaren": "Een boekjaar is het jaar",
        "/boeken": "Alle boekingen: elke euro die binnenkomt of uitgaat",
        "/boeken/nieuw": "Met een handmatige boeking leg je zelf vast",
    }
    for url, sentence in leads.items():
        assert sentence in visible_text(client.get(url).text), url


def test_confirm_dialogs_in_plain_dutch(seeded):
    html = seeded.get("/instellingen/boekjaren").text
    assert f"Periode 1 van {YEAR} vergrendelen? Daarna kun je er niets meer in boeken" in html
    assert f"Boekjaar {YEAR} afsluiten? Alle 12 periodes worden vergrendeld" in html
    assert "Periode vergrendelen" in html
