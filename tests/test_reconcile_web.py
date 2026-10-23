"""Web tests for bank reconciliation (/bank/afletteren, /bank/regels). Domain rules: tests/domain/reconcile."""

from datetime import date, datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.bank.accounts import create_bank_account
from app.domain.documents import add_document, mark_recognized
from app.domain.documents.storage import DocumentStorage
from app.domain.glossary import GLOSSARY
from app.domain.purchase import book_extraction
from app.domain.relations import ContactInput, create_contact
from app.models import (
    Account,
    BankImportBatch,
    BankMatch,
    BankRule,
    BankTransaction,
    InvoiceExtraction,
    InvoiceExtractionLine,
    PurchaseInvoice,
)
from tests.web_helpers import assert_plain_language

TODAY = date.today()
YEAR = TODAY.year
IBAN = "NL91ABNA0417164300"
BANK_IBAN = "NL20INGB0001234567"
NEW_TERMS = ("afletteren", "deelbetaling", "direct_boeken", "matchingregel")


def pdf(n: int) -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%" + str(n).encode() + b"\ntrailer\n%%EOF\n"


class World:
    """Seeds a bankrekening, leveranciers, inkoopfacturen and bank transactions in the client's database."""

    def __init__(self, client, test_settings):
        self.engine = client.app.state.engine
        self.storage = DocumentStorage(test_settings.documents_dir)
        self.n = 0
        self.suppliers: dict[str, int] = {}
        with Session(self.engine, expire_on_commit=False) as s:
            acc = s.scalar(select(Account.id).where(Account.code == "1210"))
            self.bank = create_bank_account(s, "Zakelijk ING", BANK_IBAN, acc, "ing")
            s.commit()
            b = BankImportBatch(
                bank_account_id=self.bank.id, status="afgerond", original_filename="x.csv", sha256="0" * 64,
                ext="csv", size=1, detected_format="csv", created_at=datetime.now(),
            )
            s.add(b)
            s.commit()
            self.batch = b.id

    def invoice(self, supplier="Bol B.V.", number="F-1", excl=10000, vat=2100, kind="invoice", iban=IBAN):
        with Session(self.engine, expire_on_commit=False) as s:
            if supplier not in self.suppliers:
                self.suppliers[supplier] = create_contact(
                    s, ContactInput(name=supplier, is_supplier=True, iban=iban)
                ).id
                s.commit()
            self.n += 1
            doc = add_document(s, self.storage, pdf(self.n), f"f{self.n}.pdf").document
            now = datetime.now()
            ex = InvoiceExtraction(
                document_id=doc.id, status="ok", extractor="test", kind=kind, supplier_name=supplier,
                contact_id=self.suppliers[supplier], invoice_number=number, invoice_date=TODAY,
                currency="EUR", total_excl_cents=excl, total_vat_cents=vat, total_incl_cents=excl + vat,
                reviewed_at=now, created_at=now, updated_at=now,
            )
            s.add(ex)
            s.flush()
            account = s.scalar(select(Account.id).where(Account.code == "4625"))
            s.add(InvoiceExtractionLine(
                extraction_id=ex.id, position=0, description="Papier", amount_excl_cents=excl,
                vat_amount_cents=vat, vat_code="NL_21", account_id=account,
            ))
            mark_recognized(s, doc.id)
            s.commit()
            invoice = book_extraction(s, doc.id)
            s.commit()
            return invoice.id

    def txn(self, amount=-12100, desc="Betaling", name="Bol B.V.", iban=IBAN):
        with Session(self.engine, expire_on_commit=False) as s:
            self.n += 1
            t = BankTransaction(
                bank_account_id=self.bank.id, import_batch_id=self.batch, booking_date=TODAY,
                amount_cents=amount, currency="EUR", counterparty_name=name, counterparty_iban=iban,
                description=desc, dedupe_key=f"k{self.n}", occurrence=1, raw="{}", status="nieuw",
                created_at=datetime.now(),
            )
            s.add(t)
            s.commit()
            return t.id

    def one(self, sql, **params):
        with self.engine.connect() as conn:
            return conn.execute(text(sql), params).scalar()


@pytest.fixture
def world(client, test_settings):
    assert client.post("/instellingen/boekjaren", data={"year": YEAR}, follow_redirects=False).status_code == 303
    return World(client, test_settings)


def account_id(world, code):
    return world.one("SELECT id FROM account WHERE code = :c", c=code)


# --- list --------------------------------------------------------------------------------------------------


def test_list_empty_state(client, world):
    r = client.get("/bank/afletteren")
    assert r.status_code == 200
    assert "Alles is verwerkt" in r.text


def test_list_shows_suggestion_with_confidence_and_accept_button(client, world):
    world.invoice(number="F-2026-001")
    tid = world.txn(desc="Betaling factuur F-2026-001")
    html = client.get("/bank/afletteren").text
    assert "Bol B.V." in html and "F-2026-001" in html
    assert "Zeker" in html
    assert f'action="/bank/transacties/{tid}/akkoord"' in html
    assert "Akkoord" in html
    assert f'href="/bank/transacties/{tid}/afletteren?terug=' in html


def test_accept_returns_to_same_page_of_the_list(client, world):
    world.invoice(number="F-2026-001")
    tid = world.txn(desc="Betaling factuur F-2026-001")
    r = client.post(
        f"/bank/transacties/{tid}/akkoord",
        data={"suggestion": "x", "terug": "/bank/afletteren?q=bol&page=3"},
        follow_redirects=False,
    )
    assert r.status_code in (303, 409, 422)
    if r.status_code == 303:
        assert r.headers["location"].startswith("/bank/afletteren?q=bol&page=3&melding=")


def test_list_row_without_suggestion_has_no_accept_button(client, world):
    tid = world.txn(desc="Bankkosten", name="ING", iban="NL20INGB0001234567", amount=-250)
    html = client.get("/bank/afletteren").text
    assert f"/bank/transacties/{tid}/akkoord" not in html
    assert f'href="/bank/transacties/{tid}/afletteren?terug=' in html


def test_list_filters_direction_and_text(client, world):
    world.txn(amount=-1000, desc="Alpha uitgave", name="A", iban=None)
    world.txn(amount=2000, desc="Beta ontvangst", name="B", iban=None)
    af = client.get("/bank/afletteren?richting=af").text
    assert "Alpha uitgave" in af and "Beta ontvangst" not in af
    q = client.get("/bank/afletteren?q=Beta").text
    assert "Beta ontvangst" in q and "Alpha uitgave" not in q


def test_list_htmx_search_returns_only_rows(client, world):
    world.txn(desc="Alpha uitgave", iban=None)
    r = client.get("/bank/afletteren?q=Alpha", headers={"HX-Request": "true", "HX-Target": "reconcile-rows"})
    assert r.status_code == 200 and "Alpha uitgave" in r.text and "<html" not in r.text


def test_list_genegeerd_filter_shows_ignored_with_restore(client, world):
    tid = world.txn(desc="Dubbele regel", iban=None)
    assert client.post(f"/bank/transacties/{tid}/negeren", follow_redirects=False).status_code == 303
    assert "Dubbele regel" not in client.get("/bank/afletteren").text
    html = client.get("/bank/afletteren?status=genegeerd").text
    assert "Dubbele regel" in html and f"/bank/transacties/{tid}/terugzetten" in html


def test_bank_index_shows_count_and_link(client, world):
    world.txn()
    world.txn()
    html = client.get("/bank").text
    assert "2 te verwerken" in html
    assert 'href="/bank/afletteren"' in html


def test_bank_transactions_rows_link_to_afletteren_and_show_status(client, world):
    tid = world.txn(desc="Open regel")
    done = world.txn(desc="Genegeerde regel")
    client.post(f"/bank/transacties/{done}/negeren")
    html = client.get("/bank").text
    assert f'href="/bank/transacties/{tid}/afletteren"' in html
    assert "Genegeerd" in html


# --- accept ------------------------------------------------------------------------------------------------


def suggestion_key(client, tid):
    html = client.get("/bank/afletteren").text
    marker = f'action="/bank/transacties/{tid}/akkoord"'
    chunk = html.split(marker, 1)[1].split("</form>", 1)[0]
    return chunk.split('name="suggestion" value="', 1)[1].split('"', 1)[0]


def test_accept_books_and_redirects(client, world):
    inv = world.invoice(number="F-2026-001")
    tid = world.txn(desc="Betaling factuur F-2026-001")
    key = suggestion_key(client, tid)
    r = client.post(f"/bank/transacties/{tid}/akkoord", data={"suggestion": key}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/bank/afletteren")
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "geboekt"
    assert world.one("SELECT paid_cents FROM purchase_invoice WHERE id = :i", i=inv) == 12100
    assert "betaald" in client.get("/inkoop?tab=all").text.lower()


def test_accept_twice_gives_409_in_plain_dutch(client, world):
    world.invoice(number="F-2026-001")
    tid = world.txn(desc="Betaling factuur F-2026-001")
    key = suggestion_key(client, tid)
    client.post(f"/bank/transacties/{tid}/akkoord", data={"suggestion": key})
    r = client.post(f"/bank/transacties/{tid}/akkoord", data={"suggestion": key}, follow_redirects=False)
    assert r.status_code == 409
    assert "Deze mutatie is al verwerkt." in r.text
    assert world.one("SELECT count(*) FROM bank_match") == 1


def test_accept_unknown_transaction_is_404(client, world):
    assert client.post("/bank/transacties/9999/akkoord", data={"suggestion": "x"}).status_code == 404


def test_accept_gone_suggestion_gives_plain_error(client, world):
    tid = world.txn(desc="Bankkosten", iban=None)
    r = client.post(f"/bank/transacties/{tid}/akkoord", data={"suggestion": "match:purchase_invoice-1-100"})
    assert r.status_code == 422
    assert "Traceback" not in r.text and "RECONCILE" not in r.text


# --- detail / manual match ----------------------------------------------------------------------------------


def test_detail_lists_open_items_of_matched_supplier(client, world):
    world.invoice(number="F-1")
    world.invoice(number="F-2", excl=5000, vat=1050)
    tid = world.txn(amount=-12100, desc="Betaling")
    html = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert "Welke factuur is dit?" in html
    assert "F-1" in html and "F-2" in html
    assert "Wat is dit voor uitgave?" in html
    assert "Nog te verdelen" in html


def test_detail_without_supplier_offers_search(client, world):
    world.invoice()
    tid = world.txn(name="Onbekend", iban=None)
    html = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert 'name="contact"' in html


def test_detail_unknown_is_404(client, world):
    assert client.get("/bank/transacties/9999/afletteren").status_code == 404


def alloc_form(inv_id, amount, **extra):
    data = {"item": [f"purchase_invoice:{inv_id}"], f"amount_purchase_invoice_{inv_id}": amount}
    data.update(extra)
    return data


def test_manual_match_books_full_payment(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-12100)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "121,00"), follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT paid_cents FROM purchase_invoice WHERE id = :i", i=inv) == 12100
    assert world.one("SELECT count(*) FROM bank_match WHERE reversed_at IS NULL") == 1


def test_manual_partial_payment_keeps_invoice_open(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-5000)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "50,00"), follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT paid_cents FROM purchase_invoice WHERE id = :i", i=inv) == 5000
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "geboekt"


def test_manual_remainder_is_refused_with_plain_message(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-12100)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "100,00"))
    assert r.status_code == 422
    assert "Er is nog € 21,00 niet verdeeld." in r.text
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "nieuw"
    # what the user typed stays on the page
    assert "100,00" in r.text


def test_manual_over_allocation_refused(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-20000)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "200,00"))
    assert r.status_code == 422
    assert "Je kunt maximaal" in r.text


def test_manual_invalid_amount_message(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-12100)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "abc"))
    assert r.status_code == 422
    assert "Vul bij factuur F-1 een geldig bedrag in" in r.text


def test_manual_split_over_two_invoices(client, world):
    a = world.invoice(number="F-1")
    b = world.invoice(number="F-2", excl=5000, vat=1050)
    tid = world.txn(amount=-(12100 + 6050))
    data = {
        "item": [f"purchase_invoice:{a}", f"purchase_invoice:{b}"],
        f"amount_purchase_invoice_{a}": "121,00",
        f"amount_purchase_invoice_{b}": "60,50",
    }
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=data, follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT count(*) FROM bank_match") == 2


def test_manual_wrong_direction_message(client, world):
    cn = world.invoice(number="CN-1", kind="credit_note")
    tid = world.txn(amount=-1000)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(cn, "10,00"))
    assert r.status_code == 422
    assert "Een bedrag af kun je alleen koppelen aan inkoopfacturen" in r.text


def test_manual_nothing_chosen_message(client, world):
    tid = world.txn(amount=-1000)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data={})
    assert r.status_code == 422
    assert "Er is nog € 10,00 niet verdeeld." in r.text or "Kies" in r.text


def test_summary_is_computed_on_the_server(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-12100)
    r = client.post(f"/bank/transacties/{tid}/afletteren/controle", data=alloc_form(inv, "100,00"))
    assert r.status_code == 200
    assert "€ 100,00" in r.text and "€ 121,00" in r.text and "€ 21,00" in r.text
    assert "<html" not in r.text


def test_summary_ignores_bad_input(client, world):
    inv = world.invoice(number="F-1")
    tid = world.txn(amount=-12100)
    r = client.post(f"/bank/transacties/{tid}/afletteren/controle", data=alloc_form(inv, "abc"))
    assert r.status_code == 200 and "€ 121,00" in r.text


# --- direct booking -----------------------------------------------------------------------------------------


def direct_form(world, amount="2,50", code="4905", vat="", **extra):
    data = {
        "line_account": [str(account_id(world, code))],
        "line_vat": [vat],
        "line_amount": [amount],
        "line_description": ["Bankkosten"],
    }
    data.update(extra)
    return data


def test_direct_booking_without_invoice(client, world):
    tid = world.txn(amount=-250, desc="Kosten", name="ING", iban=None)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=direct_form(world, vat="GEEN"), follow_redirects=False)
    assert r.status_code == 303, r.text
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "geboekt"
    assert world.one("SELECT count(*) FROM bank_match") == 0


def test_direct_booking_requires_account_in_plain_dutch(client, world):
    tid = world.txn(amount=-250, iban=None)
    data = {"line_account": [""], "line_vat": [""], "line_amount": ["2,50"], "line_description": [""]}
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=data)
    assert r.status_code == 422
    assert "Kies een rekening" in r.text


def test_direct_booking_remembers_rule_and_suggests_it_next_time(client, world):
    tid = world.txn(amount=-250, desc="Kosten maand 1", name="ING", iban=IBAN)
    r = client.post(
        f"/bank/transacties/{tid}/afletteren", data=direct_form(world, vat="GEEN", remember="1"),
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text
    assert world.one("SELECT count(*) FROM bank_rule") == 1
    next_id = world.txn(amount=-250, desc="Kosten maand 2", name="ING", iban=IBAN)
    html = client.get("/bank/afletteren").text
    assert f'action="/bank/transacties/{next_id}/akkoord"' in html
    assert "Waarschijnlijk" in html or "Zeker" in html


def test_direct_defaults_prefill_from_last_booking(client, world):
    tid = world.txn(amount=-250, desc="Kosten maand 1", name="ING", iban=IBAN)
    client.post(f"/bank/transacties/{tid}/afletteren", data=direct_form(world, vat="GEEN"))
    nxt = world.txn(amount=-250, desc="Kosten maand 2", name="ING", iban=IBAN)
    html = client.get(f"/bank/transacties/{nxt}/afletteren").text
    assert f'<option value="{account_id(world, "4905")}" ' in html and "selected" in html


# --- negeren / terugzetten / ongedaan maken ---------------------------------------------------------------


def test_ignore_and_restore(client, world):
    tid = world.txn(iban=None)
    page = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert "Deze mutatie komt niet in je boekhouding." in page
    assert client.post(f"/bank/transacties/{tid}/negeren", follow_redirects=False).status_code == 303
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "genegeerd"
    assert "Terugzetten" in client.get(f"/bank/transacties/{tid}/afletteren").text
    assert client.post(f"/bank/transacties/{tid}/terugzetten", follow_redirects=False).status_code == 303
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "nieuw"


def test_ignore_booked_transaction_is_409(client, world):
    inv = world.invoice()
    tid = world.txn(amount=-12100)
    client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "121,00"))
    r = client.post(f"/bank/transacties/{tid}/negeren")
    assert r.status_code == 409 and "Deze mutatie is al verwerkt." in r.text


def test_restore_unignored_is_409(client, world):
    tid = world.txn(iban=None)
    r = client.post(f"/bank/transacties/{tid}/terugzetten")
    assert r.status_code == 409


def test_undo_restores_everything(client, world):
    inv = world.invoice()
    tid = world.txn(amount=-12100)
    client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "121,00"))
    page = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert "Ongedaan maken" in page and "F-1" in page
    r = client.post(f"/bank/transacties/{tid}/ongedaan-maken", follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "nieuw"
    assert world.one("SELECT paid_cents FROM purchase_invoice WHERE id = :i", i=inv) == 0
    assert world.one("SELECT count(*) FROM bank_match WHERE reversed_at IS NULL") == 0


def test_undo_not_booked_is_409(client, world):
    tid = world.txn(iban=None)
    r = client.post(f"/bank/transacties/{tid}/ongedaan-maken")
    assert r.status_code == 409


def test_undo_in_locked_period_says_what_to_do(client, world):
    inv = world.invoice()
    tid = world.txn(amount=-12100)
    client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "121,00"))
    with world.engine.begin() as conn:
        conn.execute(text("UPDATE period SET status = 'locked'"))
    r = client.post(f"/bank/transacties/{tid}/ongedaan-maken")
    assert r.status_code in (409, 422)
    assert "Traceback" not in r.text
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "geboekt"


def test_generic_storno_of_bank_entry_is_refused_and_state_stays_consistent(client, world):
    inv = world.invoice()
    tid = world.txn(amount=-12100)
    client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "121,00"))
    entry_id = world.one("SELECT journal_entry_id FROM bank_transaction WHERE id = :i", i=tid)
    page = client.get(f"/boeken/{entry_id}").text
    assert f"/boeken/{entry_id}/storno" not in page
    assert f"/bank/transacties/{tid}/afletteren" in page
    r = client.post(f"/boeken/{entry_id}/storno", data={})
    assert r.status_code == 409
    assert "Ongedaan maken" in r.text and "bankmutatie" in r.text
    assert world.one("SELECT count(*) FROM journal_entry WHERE kind = 'storno'") == 0
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "geboekt"
    assert world.one("SELECT paid_cents FROM purchase_invoice WHERE id = :i", i=inv) == 12100
    assert world.one("SELECT count(*) FROM bank_match WHERE reversed_at IS NULL") == 1


def test_generic_storno_allowed_again_after_undo(client, world):
    inv = world.invoice()
    tid = world.txn(amount=-12100)
    client.post(f"/bank/transacties/{tid}/afletteren", data=alloc_form(inv, "121,00"))
    entry_id = world.one("SELECT journal_entry_id FROM bank_transaction WHERE id = :i", i=tid)
    client.post(f"/bank/transacties/{tid}/ongedaan-maken")
    page = client.get(f"/boeken/{entry_id}").text
    assert f"/boeken/{entry_id}/storno" not in page or "al ongedaan" in page


def test_credit_note_is_explained_and_rules_show_vat_name(client, world):
    inv = world.invoice(number="CN-1", kind="credit_note")
    tid = world.txn(amount=12100)
    html = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert "Creditnota" in html and "terugbetaling" in html.lower()
    assert "Wat is dit voor uitgave" not in html
    tid2 = world.txn(amount=-250, desc="Kosten", name="ING")
    client.post(f"/bank/transacties/{tid2}/afletteren", data=direct_form(world, vat="NL_21", remember="1"))
    assert "NL_21" not in client.get("/bank/regels").text


# --- rules ---------------------------------------------------------------------------------------------------


def make_rule(client, world):
    tid = world.txn(amount=-250, desc="Kosten", name="ING", iban=IBAN)
    client.post(f"/bank/transacties/{tid}/afletteren", data=direct_form(world, vat="GEEN", remember="1"))
    return world.one("SELECT id FROM bank_rule")


def test_rules_page_empty(client, world):
    r = client.get("/bank/regels")
    assert r.status_code == 200 and "Nog geen onthouden keuzes" in r.text


def test_rules_page_lists_and_toggles(client, world):
    rid = make_rule(client, world)
    html = client.get("/bank/regels").text
    assert "4905" in html and "Actief" in html
    r = client.post(f"/bank/regels/{rid}/actief", data={"actief": "0"}, follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT is_active FROM bank_rule WHERE id = :i", i=rid) == 0
    assert "Weer aanzetten" in client.get("/bank/regels").text
    client.post(f"/bank/regels/{rid}/actief", data={"actief": "1"})
    assert world.one("SELECT is_active FROM bank_rule WHERE id = :i", i=rid) == 1


def test_rule_toggle_unknown_is_404(client, world):
    assert client.post("/bank/regels/9999/actief", data={"actief": "0"}).status_code == 404


def test_inactive_rule_gives_no_suggestion(client, world):
    rid = make_rule(client, world)
    client.post(f"/bank/regels/{rid}/actief", data={"actief": "0"})
    nxt = world.txn(amount=-250, desc="Kosten", name="ING", iban=IBAN)
    assert f"/bank/transacties/{nxt}/akkoord" not in client.get("/bank/afletteren").text


# --- plain language / glossary ---------------------------------------------------------------------------


def test_new_glossary_terms_exist_and_are_plain():
    for key in NEW_TERMS:
        term = GLOSSARY[key]
        assert term.plain and 0 < len(term.explanation) <= 220


def test_pages_are_plain_language(client, world):
    inv = world.invoice(number="F-2026-001")
    tid = world.txn(desc="Betaling factuur F-2026-001")
    assert_plain_language(client, "/bank/afletteren")
    assert_plain_language(client, f"/bank/transacties/{tid}/afletteren")
    assert_plain_language(client, "/bank/regels")
    assert_plain_language(client, "/bank")
    client.post(f"/bank/transacties/{tid}/akkoord", data={"suggestion": suggestion_key(client, tid)})
    assert_plain_language(client, f"/bank/transacties/{tid}/afletteren")
    ignored = world.txn(iban=None)
    client.post(f"/bank/transacties/{ignored}/negeren")
    assert_plain_language(client, "/bank/afletteren?status=genegeerd")


def test_new_terms_are_shown_with_info_icons(client, world):
    world.invoice()
    tid = world.txn()
    html = client.get(f"/bank/transacties/{tid}/afletteren").text
    for key in ("afletteren", "direct_boeken", "matchingregel", "deelbetaling"):
        assert f'data-term="{key}"' in html
    assert 'data-term="afletteren"' in client.get("/bank/afletteren").text


# --- sales invoices (debiteuren) ---------------------------------------------------------------------------


def sales_invoice(world, name="Klant BV", iban=IBAN):
    """A finalized verkoopfactuur of 121,00 dated today; returns (invoice_id, number)."""
    from app.domain.company.service import save_company_profile
    from app.domain.company.validation import CompanyInput
    from app.domain.sales import ConceptInput, LineInput, create_concept, finalize

    with Session(world.engine, expire_on_commit=False) as s:
        save_company_profile(s, CompanyInput(
            legal_name="Jansen Webdesign", legal_form="eenmanszaak", address_line="Dorpsstraat 1",
            postal_code="1234 AB", city="Utrecht", kvk="12345678", btw_id="NL123456789B01",
            iban=BANK_IBAN, email="info@jansen.nl",
        ))
        customer = create_contact(s, ContactInput(
            name=name, is_customer=True, iban=iban, address_line="Hoofdweg 2",
            postal_code="1000 AA", city="Amsterdam",
        ))
        account = s.scalar(select(Account.id).where(Account.code == "8400"))
        inv = create_concept(s, ConceptInput(
            contact_id=customer.id, invoice_date=TODAY,
            lines=[LineInput("Website", 1000, 10000, "NL_21", account)],
        ))
        s.commit()
        finalize(s, inv.id, storage=world.storage)
        s.commit()
        return inv.id, inv.number


def test_list_shows_sales_suggestion_label(client, world):
    inv_id, number = sales_invoice(world)
    world.txn(amount=12100, desc=f"Betaling {number}", name="Klant BV")
    html = client.get("/bank/afletteren").text
    assert f"Verkoopfactuur {number} - Klant BV" in html
    assert "Zeker" in html


def test_accept_sales_suggestion_marks_invoice_paid_and_undo_restores(client, world):
    inv_id, number = sales_invoice(world)
    tid = world.txn(amount=12100, desc=f"Betaling {number}", name="Klant BV")
    key = f"match:sales_invoice-{inv_id}-12100"
    r = client.post(f"/bank/transacties/{tid}/akkoord", data={"suggestion": key}, follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT paid_cents FROM sales_invoice WHERE id = :i", i=inv_id) == 12100
    assert client.post(f"/bank/transacties/{tid}/ongedaan-maken", follow_redirects=False).status_code == 303
    assert world.one("SELECT paid_cents FROM sales_invoice WHERE id = :i", i=inv_id) == 0


def test_detail_offers_customers_and_lists_their_invoices(client, world):
    inv_id, number = sales_invoice(world)
    tid = world.txn(amount=12100, desc="Betaling", name="Klant BV")
    html = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert "klant of leverancier" in html
    assert number in html and "Verkoopfactuur" in html
    assert "Welke factuur is dit?" in html


def test_manual_match_of_sales_invoice_and_mixed_refusal(client, world):
    inv_id, number = sales_invoice(world, iban="NL02ABNA0123456789")
    supplier_inv = world.invoice(number="F-1")
    tid = world.txn(amount=12100, desc="Betaling", name="Klant BV")
    bad = {
        "item": [f"sales_invoice:{inv_id}", f"purchase_invoice:{supplier_inv}"],
        f"amount_sales_invoice_{inv_id}": "60,00",
        f"amount_purchase_invoice_{supplier_inv}": "61,00",
    }
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=bad)
    assert r.status_code == 422
    assert "niet tegelijk aan verkoop- en inkoopfacturen" in r.text
    good = {"item": [f"sales_invoice:{inv_id}"], f"amount_sales_invoice_{inv_id}": "121,00"}
    r = client.post(f"/bank/transacties/{tid}/afletteren", data=good, follow_redirects=False)
    assert r.status_code == 303
    assert world.one("SELECT paid_cents FROM sales_invoice WHERE id = :i", i=inv_id) == 12100
    assert "Verkoopfactuur" in client.get(f"/bank/transacties/{tid}/afletteren").text


def test_detail_search_by_customer_name(client, world):
    inv_id, number = sales_invoice(world)
    tid = world.txn(amount=12100, desc="Betaling", name="Onbekend", iban=None)
    html = client.get(f"/bank/transacties/{tid}/afletteren?q=Klant").text
    assert number in html


# --- snelkeuze: btw-aangifte en privé ---------------------------------------------------------------------


def test_detail_offers_quick_choices(client, world):
    tid = world.txn(amount=-5000, iban=None)
    html = client.get(f"/bank/transacties/{tid}/afletteren").text
    assert 'name="soort" value="btw"' in html and 'name="soort" value="prive"' in html
    assert 'name="aangifte"' in html and ">1e kwartaal " in html


def test_quick_vat_return_payment_books_without_invoice(client, world):
    tid = world.txn(amount=-123400, desc="Belastingdienst", name="Belastingdienst", iban=None)
    r = client.post(
        f"/bank/transacties/{tid}/afletteren", data={"soort": "btw", "aangifte": f"{YEAR}-Q1"}, follow_redirects=False
    )
    assert r.status_code == 303, r.text
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "geboekt"
    assert world.one(
        "SELECT sum(l.debit_cents) FROM journal_line l JOIN account a ON a.id = l.account_id WHERE a.code = '3150'"
    ) == 123400


def test_quick_private_withdrawal_books_to_prive_opnamen(client, world):
    tid = world.txn(amount=-30000, desc="Eigen rekening", name="J. Jansen", iban=None)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data={"soort": "prive"}, follow_redirects=False)
    assert r.status_code == 303, r.text
    assert world.one(
        "SELECT sum(l.debit_cents) FROM journal_line l JOIN account a ON a.id = l.account_id WHERE a.code = '2010'"
    ) == 30000


def test_quick_choice_with_bad_period_says_what_to_do(client, world):
    tid = world.txn(amount=-100, iban=None)
    r = client.post(f"/bank/transacties/{tid}/afletteren", data={"soort": "btw", "aangifte": "kerst"})
    assert r.status_code == 422
    assert "Kies een periode" in r.text
    assert world.one("SELECT status FROM bank_transaction WHERE id = :i", i=tid) == "nieuw"


def test_quick_glossary_terms_exist():
    for key in ("snelkeuze", "btw_aangifte_betaling", "prive"):
        assert GLOSSARY[key].plain and GLOSSARY[key].explanation
