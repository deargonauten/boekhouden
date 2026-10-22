"""Web tests for /verkoop. Sales logic is tested in tests/sales; here: routes, forms, PDF headers,
plain-language screens."""

import re
from datetime import date, timedelta

import pytest

from tests.web_helpers import assert_plain_language

TODAY = date.today()
YEAR = TODAY.year
OLD = date(YEAR - 1, 12, 1)  # always in the past

COMPANY = {
    "legal_name": "Jansen Webdesign", "legal_form": "eenmanszaak", "address_line": "Dorpsstraat 1",
    "postal_code": "1234ab", "city": "Utrecht", "country": "NL", "kvk": "12345678",
    "btw_id": "NL123456789B01", "iban": "NL91ABNA0417164300",
}


def line(desc="Website", qty="1", price="100,00", vat="NL_21", account="", unit="stuk"):
    return {"description": desc, "quantity": qty, "price": price, "vat": vat, "account": account, "unit": unit}


def form(contact_id, lines=None, day=TODAY, **over):
    lines = lines if lines is not None else [line()]
    data = {
        "contact_id": str(contact_id), "invoice_date": day.isoformat(), "payment_term_days": "",
        "due_date": "", "service_date": "", "reference": "", "note": "",
        "line_description": [l["description"] for l in lines],
        "line_quantity": [l["quantity"] for l in lines],
        "line_unit": [l["unit"] for l in lines],
        "line_price": [l["price"] for l in lines],
        "line_vat": [l["vat"] for l in lines],
        "line_account": [l["account"] for l in lines],
        "line_original": ["" for _ in lines],
    }
    data.update(over)
    return data


@pytest.fixture
def shop(client):
    """Boekjaren, own company data and one klant with a complete address."""
    for year in (YEAR - 1, YEAR):
        assert client.post("/instellingen/boekjaren", data={"year": year}).status_code in (200, 303)
    r = client.post("/instellingen/bedrijfsgegevens", data=COMPANY, follow_redirects=False)
    assert r.status_code == 303
    r = client.post("/relaties/nieuw", follow_redirects=False, data={
        "name": "Klant BV", "is_customer": "1", "address_line": "Hoofdweg 2", "postal_code": "1000 AA",
        "city": "Amsterdam", "email": "klant@example.nl",
    })
    assert r.status_code == 303
    client.customer_id = int(r.headers["location"].rsplit("=", 1)[1])
    return client


def make_concept(c, **kw):
    lines = kw.pop("lines", None)
    r = c.post("/verkoop/nieuw", data=form(c.customer_id, lines, **kw), follow_redirects=False)
    assert r.status_code == 303, r.text
    return int(re.search(r"/verkoop/(\d+)", r.headers["location"]).group(1))


def make_final(c, **kw):
    invoice_id = make_concept(c, **kw)
    r = c.post(f"/verkoop/{invoice_id}/definitief", follow_redirects=False)
    assert r.status_code == 303, r.text
    return invoice_id


# --- overview ---------------------------------------------------------------------------------------
def test_verkoop_is_no_longer_a_placeholder_and_shows_empty_state(client):
    html = client.get("/verkoop").text
    assert "Je hebt nog geen facturen" in html
    assert 'href="/verkoop/nieuw"' in html and "Maak je eerste factuur" in html


def test_overview_lists_concept_and_final_documents(shop):
    concept = make_concept(shop)
    final = make_final(shop, lines=[line(price="200,00")])
    html = shop.get("/verkoop").text
    assert "Nog geen nummer" in html and f"{YEAR}-0001" in html
    assert "Concept" in html and "Klant BV" in html
    assert f"/verkoop/{concept}" in html and f"/verkoop/{final}/pdf" in html
    assert "Totaal openstaand" in html and "Concepten" in html


def test_status_filter_and_search(shop):
    make_concept(shop)
    make_final(shop)
    assert f"{YEAR}-0001" not in shop.get("/verkoop?status=concept").text
    assert f"{YEAR}-0001" in shop.get("/verkoop?status=openstaand").text
    assert "Geen facturen gevonden" in shop.get("/verkoop?q=zzzz").text
    assert f"{YEAR}-0001" in shop.get(f"/verkoop?q={YEAR}-0001").text


def test_debiteuren_tab_and_klant_detail(shop):
    make_final(shop, lines=[line(price="100,00")])
    html = shop.get("/verkoop/debiteuren").text
    assert "Klant BV" in html and "1-30 dagen" in html and "Meer dan 90 dagen" in html
    assert "€ 121,00" in html
    detail = shop.get(f"/verkoop/debiteuren/{shop.customer_id}").text
    assert f"{YEAR}-0001" in detail
    assert shop.get("/verkoop/debiteuren/9999").status_code == 404


# --- concept editor ---------------------------------------------------------------------------------
def test_new_form_prefills_defaults(shop):
    html = shop.get(f"/verkoop/nieuw?klant={shop.customer_id}").text
    assert TODAY.isoformat() in html
    assert 'placeholder="30"' in html
    assert "Voorstel: 8000" in html
    assert 'value="stuk"' in html


def test_create_concept_saves_and_redirects(shop):
    invoice_id = make_concept(shop, reference="PO-1", note="Bedankt")
    html = shop.get(f"/verkoop/{invoice_id}?melding=opgeslagen").text
    assert "De factuur is opgeslagen als concept." in html
    assert 'value="PO-1"' in html and "Bedankt" in html
    assert "Totaal inclusief BTW" in html and "€ 121,00" in html


def test_klant_term_prefills_placeholder(shop):
    shop.post(f"/relaties/{shop.customer_id}/bewerken", data={
        "name": "Klant BV", "is_customer": "1", "payment_term_days": "14"})
    assert 'placeholder="14"' in shop.get(f"/verkoop/nieuw?klant={shop.customer_id}").text


def test_due_date_follows_term_unless_manual(shop):
    invoice_id = make_concept(shop, payment_term_days="10")
    assert (TODAY + timedelta(days=10)).isoformat() in shop.get(f"/verkoop/{invoice_id}").text
    manual = (TODAY + timedelta(days=45)).isoformat()
    r = shop.post(f"/verkoop/{invoice_id}", data=form(shop.customer_id, payment_term_days="10",
                                                       due_date=manual, due_date_manual="1"), follow_redirects=False)
    assert r.status_code == 303
    assert f'name="due_date" value="{manual}"' in shop.get(f"/verkoop/{invoice_id}").text


def test_save_edits_replaces_lines(shop):
    invoice_id = make_concept(shop)
    r = shop.post(f"/verkoop/{invoice_id}", data=form(shop.customer_id, [line("A", "2", "10,50", "NL_9"), line("B")]),
                  follow_redirects=False)
    assert r.status_code == 303
    html = shop.get(f"/verkoop/{invoice_id}").text
    assert 'value="A"' in html and 'value="B"' in html and 'value="10,50"' in html


def test_empty_rows_are_skipped(shop):
    invoice_id = make_concept(shop, lines=[line(), line("", "1", "")])
    assert shop.get(f"/verkoop/{invoice_id}").text.count('name="line_description"') == 1


def test_line_partial_adds_a_row(shop):
    html = shop.get("/verkoop/regel?vat_code=NL_9").text
    assert 'name="line_description"' in html and '<option value="NL_9" selected>' in html


def test_live_totals_partial(shop):
    r = shop.post("/verkoop/totalen", data=form(shop.customer_id, [line(price="100,00"), line("x", "2", "50,00", "NL_9")]))
    assert r.status_code == 200
    assert "€ 200,00" in r.text and "BTW 21% over € 100,00" in r.text and "€ 21,00" in r.text
    assert "BTW 9% over € 100,00" in r.text and "€ 9,00" in r.text and "€ 230,00" in r.text


def test_live_totals_ignore_unreadable_rows(shop):
    r = shop.post("/verkoop/totalen", data=form(shop.customer_id, [line(price="abc"), line("ok", "1", "10,00")]))
    assert r.status_code == 200 and "€ 12,10" in r.text


def test_bad_price_gives_plain_422_and_keeps_input(shop):
    r = shop.post("/verkoop/nieuw", data=form(shop.customer_id, [line(price="abc")]))
    assert r.status_code == 422
    assert 'role="alert"' in r.text and "Regel 1:" in r.text and "geen geldig bedrag" in r.text
    assert 'value="abc"' in r.text


def test_missing_klant_message(shop):
    r = shop.post("/verkoop/nieuw", data=form(""))
    assert r.status_code == 422 and "Kies eerst een klant" in r.text


def test_bad_date_message(shop):
    r = shop.post("/verkoop/nieuw", data=form(shop.customer_id, invoice_date="morgen"))
    assert r.status_code == 422 and "Vul een geldige datum in bij factuurdatum" in r.text


def test_delete_concept(shop):
    invoice_id = make_concept(shop)
    r = shop.post(f"/verkoop/{invoice_id}/verwijderen", follow_redirects=False)
    assert r.status_code == 303 and "melding=verwijderd" in r.headers["location"]
    assert shop.get(f"/verkoop/{invoice_id}").status_code == 404


def test_unknown_invoice_is_404(shop):
    assert shop.get("/verkoop/9999").status_code == 404
    assert shop.get("/verkoop/9999/pdf").status_code == 404


# --- definitief maken ---------------------------------------------------------------------------------
def test_confirmation_page_previews_the_booking(shop):
    invoice_id = make_concept(shop)
    html = shop.get(f"/verkoop/{invoice_id}/definitief").text
    assert "Zo wordt het geboekt" in html and "€ 100,00" in html and "€ 21,00" in html and "€ 121,00" in html
    assert "Klant moet nog betalen" in html
    assert "Dit kun je daarna niet meer wijzigen" in html


def test_save_and_finalize_button_goes_to_confirmation(shop):
    r = shop.post("/verkoop/nieuw", data={**form(shop.customer_id), "actie": "definitief"}, follow_redirects=False)
    assert r.headers["location"].endswith("/definitief")


def test_finalize_assigns_number_and_shows_detail(shop):
    first = make_final(shop)
    second = make_final(shop)
    html = shop.get(f"/verkoop/{first}?melding=definitief").text
    assert f"{YEAR}-0001" in html and "De factuur is definitief" in html and "Boeking" in html
    assert f"{YEAR}-0002" in shop.get(f"/verkoop/{second}").text


def test_finalized_invoice_cannot_be_edited_or_deleted(shop):
    invoice_id = make_final(shop)
    r = shop.post(f"/verkoop/{invoice_id}", data=form(shop.customer_id))
    assert r.status_code == 422 and "definitief en kan niet meer worden gewijzigd" in r.text
    r = shop.post(f"/verkoop/{invoice_id}/verwijderen")
    assert r.status_code == 422 and "definitief" in r.text
    assert shop.get(f"/verkoop/{invoice_id}/definitief", follow_redirects=False).status_code == 303


def test_finalize_without_klant_address_names_what_to_do(shop):
    r = shop.post("/relaties/nieuw", follow_redirects=False, data={"name": "Zonder Adres", "is_customer": "1"})
    cid = int(r.headers["location"].rsplit("=", 1)[1])
    invoice_id = int(re.search(r"/verkoop/(\d+)", shop.post("/verkoop/nieuw", data=form(cid), follow_redirects=False)
                               .headers["location"]).group(1))
    r = shop.post(f"/verkoop/{invoice_id}/definitief")
    assert r.status_code == 422
    assert "Vul het adres van Zonder Adres in bij Relaties" in r.text
    assert f'/relaties/{cid}/bewerken' in r.text


def test_finalize_without_company_data_links_to_settings(client):
    for year in (YEAR - 1, YEAR):
        client.post("/instellingen/boekjaren", data={"year": year})
    r = client.post("/relaties/nieuw", follow_redirects=False, data={
        "name": "K", "is_customer": "1", "address_line": "x 1", "postal_code": "1000 AA", "city": "A"})
    cid = int(r.headers["location"].rsplit("=", 1)[1])
    client.customer_id = cid
    invoice_id = make_concept(client)
    r = client.post(f"/verkoop/{invoice_id}/definitief")
    assert r.status_code == 422 and "/instellingen/bedrijfsgegevens" in r.text and 'role="alert"' in r.text


def test_zero_total_is_refused(shop):
    invoice_id = make_concept(shop, lines=[line(price="0,00")])
    r = shop.post(f"/verkoop/{invoice_id}/definitief")
    assert r.status_code == 422 and "Het totaal is €0,00" in r.text


def test_date_order_guard(shop):
    make_final(shop)
    invoice_id = make_concept(shop, day=TODAY - timedelta(days=3)) if (TODAY - timedelta(days=3)).year == YEAR else None
    if invoice_id is None:
        pytest.skip("early January: no earlier date in this year")
    r = shop.post(f"/verkoop/{invoice_id}/definitief")
    assert r.status_code == 422 and "Er is al een factuur met datum" in r.text


def test_locked_period_is_409(shop):
    invoice_id = make_concept(shop)
    from sqlalchemy import text

    with shop.app.state.engine.begin() as conn:
        conn.execute(text("UPDATE period SET status='locked' WHERE 1=1"))
    r = shop.post(f"/verkoop/{invoice_id}/definitief")
    assert r.status_code == 409 and 'role="alert"' in r.text
    assert "Nog geen nummer" in shop.get("/verkoop").text  # nothing was numbered


# --- PDF ---------------------------------------------------------------------------------------------
def test_pdf_download_headers_and_content(shop):
    invoice_id = make_final(shop)
    r = shop.get(f"/verkoop/{invoice_id}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert f'filename="Factuur-{YEAR}-0001.pdf"' in r.headers["content-disposition"]
    assert r.content.startswith(b"%PDF")
    again = shop.get(f"/verkoop/{invoice_id}/pdf")
    assert again.content == r.content  # the stored file is served, not re-rendered


def test_concept_pdf_is_a_marked_preview(shop):
    from io import BytesIO

    from pypdf import PdfReader

    invoice_id = make_concept(shop)
    r = shop.get(f"/verkoop/{invoice_id}/pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    text = " ".join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
    assert "CONCEPT" in text and "Klant BV" in text


# --- creditnota --------------------------------------------------------------------------------------
def test_credit_note_flow(shop):
    invoice_id = make_final(shop, lines=[line("A", "2", "100,00")])
    assert "Creditnota maken" in shop.get(f"/verkoop/{invoice_id}").text
    confirm = shop.get(f"/verkoop/{invoice_id}/creditnota")
    assert confirm.status_code == 200 and "Wat gebeurt er?" in confirm.text
    r = shop.post(f"/verkoop/{invoice_id}/creditnota", follow_redirects=False)
    assert r.status_code == 303 and "melding=creditnota" in r.headers["location"]
    credit_id = int(re.search(r"/verkoop/(\d+)", r.headers["location"]).group(1))
    editor = shop.get(r.headers["location"]).text
    assert "Creditnota bewerken" in editor and 'value="2"' in editor and 'name="line_original"' in editor
    original_line = re.search(r'name="line_original" value="(\d+)"', editor).group(1)
    data = {**form(shop.customer_id, [line("A", "1", "100,00")]), "line_original": [original_line]}
    assert shop.post(f"/verkoop/{credit_id}", data=data, follow_redirects=False).status_code == 303
    r = shop.post(f"/verkoop/{credit_id}/definitief", follow_redirects=False)
    assert r.status_code == 303
    detail = shop.get(f"/verkoop/{credit_id}").text
    assert f"{YEAR}-0002" in detail and f"{YEAR}-0001" in detail
    assert "Creditnota" in detail
    pdf = shop.get(f"/verkoop/{credit_id}/pdf")
    assert f'filename="Creditnota-{YEAR}-0002.pdf"' in pdf.headers["content-disposition"]
    original = shop.get(f"/verkoop/{invoice_id}").text
    assert f"{YEAR}-0002" in original  # linked credit note


def test_over_crediting_is_refused_in_plain_dutch(shop):
    invoice_id = make_final(shop, lines=[line("A", "1", "100,00")])
    r = shop.post(f"/verkoop/{invoice_id}/creditnota", follow_redirects=False)
    credit_id = int(re.search(r"/verkoop/(\d+)", r.headers["location"]).group(1))
    editor = shop.get(f"/verkoop/{credit_id}").text
    original_line = re.search(r'name="line_original" value="(\d+)"', editor).group(1)
    data = {**form(shop.customer_id, [line("A", "5", "100,00")]), "line_original": [original_line]}
    r = shop.post(f"/verkoop/{credit_id}", data=data)
    assert r.status_code == 422 and "Je kunt maximaal 1 van deze regel crediteren" in r.text


def test_no_credit_button_on_a_concept_or_credit_note(shop):
    invoice_id = make_concept(shop)
    assert shop.get(f"/verkoop/{invoice_id}/creditnota").status_code == 422


# --- herinnering -------------------------------------------------------------------------------------
def test_reminder_flow(shop):
    invoice_id = make_final(shop, day=OLD, payment_term_days="5")
    assert "Betalingsherinnering maken" in shop.get(f"/verkoop/{invoice_id}").text
    page = shop.get(f"/verkoop/{invoice_id}/herinnering")
    assert page.status_code == 200
    assert "Betalingsherinnering voor Klant BV" in page.text and f"{YEAR - 1}-0001" in page.text
    assert "mailto:klant@example.nl" in page.text
    r = shop.post(f"/verkoop/{invoice_id}/herinnering", data={"reminder_date": TODAY.isoformat(),
                  "new_due_date": (TODAY + timedelta(days=14)).isoformat()}, follow_redirects=False)
    assert r.status_code == 303 and "melding=herinnering" in r.headers["location"]
    detail = shop.get(r.headers["location"]).text
    assert "De herinnering is gemaakt" in detail and "Download de herinnering als PDF" in detail
    rid = re.search(r"/verkoop/herinneringen/(\d+)/pdf", detail).group(1)
    pdf = shop.get(f"/verkoop/herinneringen/{rid}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert "Herinnering 1" in detail
    assert "Tweede herinnering" in shop.get(f"/verkoop/{invoice_id}/herinnering").text
    assert "Herinnering gemaakt" in shop.get("/verkoop").text
    assert shop.get("/verkoop/herinneringen/9999/pdf").status_code == 404


def test_reminder_not_possible_when_not_overdue(shop):
    invoice_id = make_final(shop)
    assert "Betalingsherinnering maken" not in shop.get(f"/verkoop/{invoice_id}").text
    r = shop.get(f"/verkoop/{invoice_id}/herinnering")
    assert r.status_code == 409 and "Deze factuur is nog niet te laat." in r.text
    r = shop.post(f"/verkoop/{invoice_id}/herinnering")
    assert r.status_code == 422 and "Deze factuur is nog niet te laat." in r.text


def test_reminder_new_due_date_must_be_later(shop):
    invoice_id = make_final(shop, day=OLD, payment_term_days="5")
    r = shop.post(f"/verkoop/{invoice_id}/herinnering",
                  data={"reminder_date": TODAY.isoformat(), "new_due_date": TODAY.isoformat()})
    assert r.status_code == 422 and "De nieuwe vervaldatum moet na de datum" in r.text


# --- relations and ledger links -----------------------------------------------------------------------
def test_relation_form_accepts_and_validates_payment_term(client):
    base = {"name": "Klant", "is_customer": "1"}
    r = client.post("/relaties/nieuw", data={**base, "payment_term_days": "400"})
    assert r.status_code == 422 and "betaaltermijn is een aantal dagen tussen 0 en 365" in r.text
    r = client.post("/relaties/nieuw", data={**base, "payment_term_days": "abc"})
    assert r.status_code == 422
    r = client.post("/relaties/nieuw", data={**base, "payment_term_days": "0"}, follow_redirects=False)
    assert r.status_code == 303
    cid = r.headers["location"].rsplit("=", 1)[1]
    html = client.get(f"/relaties/{cid}/bewerken").text
    assert re.search(r'name="payment_term_days" value="0"', html)  # 0 is kept, not shown empty


def test_relation_without_term_stays_empty(client):
    r = client.post("/relaties/nieuw", data={"name": "Klant", "is_customer": "1"}, follow_redirects=False)
    cid = r.headers["location"].rsplit("=", 1)[1]
    assert re.search(r'name="payment_term_days" value=""', client.get(f"/relaties/{cid}/bewerken").text)


def test_ledger_entry_links_to_the_invoice(shop):
    invoice_id = make_final(shop)
    detail = shop.get(f"/verkoop/{invoice_id}").text
    entry_url = re.search(r'href="(/boeken/\d+)"', detail).group(1)
    assert f'href="/verkoop/{invoice_id}"' in shop.get(entry_url).text


# --- plain language ----------------------------------------------------------------------------------
def test_sales_pages_are_plain_language(shop):
    concept = make_concept(shop)
    final = make_final(shop, lines=[line(price="150,00")])
    credit_r = shop.post(f"/verkoop/{final}/creditnota", follow_redirects=False)
    credit = int(re.search(r"/verkoop/(\d+)", credit_r.headers["location"]).group(1))
    urls = [
        "/verkoop", "/verkoop?status=concept", "/verkoop?q=zzz", "/verkoop/debiteuren",
        f"/verkoop/debiteuren/{shop.customer_id}", "/verkoop/nieuw", f"/verkoop/{concept}",
        f"/verkoop/{concept}/definitief", f"/verkoop/{final}", f"/verkoop/{final}/creditnota",
        f"/verkoop/{credit}", f"/verkoop/{credit}/definitief", f"/relaties/{shop.customer_id}/bewerken",
    ]
    for url in urls:
        assert_plain_language(shop, url)


def test_reminder_and_empty_pages_are_plain_language(client, shop):
    invoice_id = make_final(shop, day=OLD, payment_term_days="5")
    assert_plain_language(shop, f"/verkoop/{invoice_id}")
    assert_plain_language(shop, f"/verkoop/{invoice_id}/herinnering")


def test_empty_sales_pages_are_plain_language(client):
    assert_plain_language(client, "/verkoop")
    assert_plain_language(client, "/verkoop/debiteuren")
    assert_plain_language(client, "/verkoop/nieuw")
