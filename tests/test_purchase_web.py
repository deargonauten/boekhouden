"""Web tests for /inkoop (Crediteuren). Booking logic is tested in tests/purchase."""

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.documents import add_document, mark_recognized
from app.domain.documents.storage import DocumentStorage
from app.domain.glossary import GLOSSARY
from app.domain.ledger import reverse_entry
from app.domain.purchase import book_extraction, open_by_supplier
from app.domain.relations import ContactInput, create_contact
from app.models import Account, InvoiceExtraction, InvoiceExtractionLine
from tests.web_helpers import assert_plain_language

TODAY = date.today()
YEAR = TODAY.year


def pdf(n: int) -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%" + str(n).encode() + b"\ntrailer\n%%EOF\n"


class Booker:
    """Books purchase invoices straight through the domain service into the client's database."""

    def __init__(self, client, test_settings):
        self.engine = client.app.state.engine
        self.storage = DocumentStorage(test_settings.documents_dir)
        self.n = 0
        self.suppliers: dict[str, int] = {}

    def book(self, supplier="Bol B.V.", number="F-1", kind="invoice", excl=10000, vat=2100, due=None, storno=False):
        with Session(self.engine, expire_on_commit=False) as s:
            if supplier not in self.suppliers:
                self.suppliers[supplier] = create_contact(s, ContactInput(name=supplier, is_supplier=True)).id
                s.commit()
            self.n += 1
            doc = add_document(s, self.storage, pdf(self.n), f"f{self.n}.pdf").document
            now = datetime.now()
            ex = InvoiceExtraction(
                document_id=doc.id, status="ok", extractor="test", kind=kind, supplier_name=supplier,
                contact_id=self.suppliers[supplier], invoice_number=number, invoice_date=TODAY, due_date=due,
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
            if storno:
                reverse_entry(s, invoice.journal_entry_id)
            s.commit()
            return invoice


@pytest.fixture
def booker(client, test_settings):
    assert client.post("/instellingen/boekjaren", data={"year": YEAR}, follow_redirects=False).status_code == 303
    return Booker(client, test_settings)


def test_inkoop_is_not_the_placeholder(client):
    r = client.get("/inkoop")
    assert r.status_code == 200
    assert "nog in ontwikkeling" not in r.text


def test_empty_state_links_to_inbox(client):
    html = client.get("/inkoop").text
    assert "Je hebt nog geen inkoopfacturen" in html
    assert 'href="/inbox"' in html


def test_stat_cards_and_open_per_supplier(client, booker):
    booker.book("Bol B.V.", "A1")
    booker.book("Bol B.V.", "A2")
    booker.book("Kantoor Plaza", "K1", excl=20000, vat=4200)
    html = client.get("/inkoop").text
    assert "Totaal openstaand" in html
    assert "484,00" in html
    assert "Bol B.V." in html and "Kantoor Plaza" in html
    assert "Openstaand per leverancier" in html and "Alle inkoopfacturen" in html


def test_all_tab_lists_invoices_with_links(client, booker):
    inv = booker.book("Bol B.V.", "A1")
    html = client.get("/inkoop?tab=all").text
    assert "A1" in html
    assert f'href="/boeken/{inv.journal_entry_id}"' in html
    assert f'href="/inbox/{inv.document_id}"' in html


def test_overdue_pill(client, booker):
    booker.book("Bol B.V.", "LATE", due=TODAY - timedelta(days=5))
    booker.book("Bol B.V.", "OK", due=TODAY + timedelta(days=5))
    html = client.get("/inkoop?tab=all").text
    assert html.count("Te laat") == 1


def test_search_by_supplier_and_number(client, booker):
    booker.book("Bol B.V.", "A1")
    booker.book("Kantoor Plaza", "K1")
    html = client.get("/inkoop?tab=all&q=kantoor").text
    assert "Kantoor Plaza" in html and "Bol B.V." not in html
    html = client.get("/inkoop?tab=all&q=A1").text
    assert "Bol B.V." in html and "Kantoor Plaza" not in html


def test_search_without_hits_is_plain(client, booker):
    booker.book("Bol B.V.", "A1")
    html = client.get("/inkoop?tab=all&q=zzzz").text
    assert "Geen inkoopfacturen gevonden" in html


def test_storno_invoice_shown_as_gestorneerd_and_excluded(client, booker):
    booker.book("Bol B.V.", "A1")
    booker.book("Weg B.V.", "W1", excl=50000, vat=10500, storno=True)
    assert "Gestorneerd" in client.get("/inkoop?tab=all").text
    open_html = client.get("/inkoop").text
    assert "Weg B.V." not in open_html
    assert "121,00" in open_html and "605,00" not in open_html


def test_credit_note_reduces_open_amount(client, booker):
    booker.book("Bol B.V.", "A1")
    booker.book("Bol B.V.", "C1", kind="credit_note", excl=5000, vat=1050)
    html = client.get("/inkoop").text
    assert "60,50" in html  # 121,00 - 60,50


def test_melding_geboekt_notice(client, booker):
    inv = booker.book("Bol B.V.", "A1")
    html = client.get(f"/inkoop?melding=geboekt&boeking={inv.journal_entry_id}").text
    assert 'role="status"' in html
    assert f'href="/boeken/{inv.journal_entry_id}"' in html


def test_pagination_counter(client, booker):
    for i in range(3):
        booker.book("Bol B.V.", f"N{i}")
    assert "Toont 1-3 van 3" in client.get("/inkoop?tab=all").text


def test_3000_balance_equals_open_total(client, booker):
    booker.book("Bol B.V.", "A1")
    booker.book("Kantoor Plaza", "K1", excl=20000, vat=4200)
    booker.book("Weg B.V.", "W1", storno=True)
    with client.app.state.engine.connect() as conn:
        balance = conn.execute(text(
            "SELECT COALESCE(SUM(l.credit_cents),0) - COALESCE(SUM(l.debit_cents),0) FROM journal_line l "
            "JOIN account a ON a.id = l.account_id WHERE a.code = '3000'"
        )).scalar()
    with Session(client.app.state.engine) as s:
        assert open_by_supplier(s).total_open_cents == balance == 12100 + 24200


def test_glossary_has_new_terms():
    for key in ("inkoopfactuur", "goedkeuren_boeken", "openstaand", "voorbelasting", "leerfunctie", "crediteuren"):
        t = GLOSSARY[key]
        assert t.plain and len(t.explanation) <= 220


def test_glossary_wording():
    assert "storno" in GLOSSARY["goedkeuren_boeken"].explanation.lower()
    assert "1400" in GLOSSARY["voorbelasting"].explanation
    assert GLOSSARY["openstaand"].plain == "Nog te betalen"
    assert GLOSSARY["leerfunctie"].plain == "Onthouden per leverancier"


@pytest.mark.parametrize("url", ["/inkoop", "/inkoop?tab=all", "/inkoop?q=zzz", "/inkoop?melding=geboekt"])
def test_empty_pages_are_plain_language(client, url):
    assert_plain_language(client, url)


def test_filled_pages_are_plain_language(client, booker):
    booker.book("Bol B.V.", "A1", due=TODAY - timedelta(days=1))
    booker.book("Weg B.V.", "W1", storno=True)
    for url in ("/inkoop", "/inkoop?tab=all", "/inkoop?tab=all&q=bol"):
        assert_plain_language(client, url)
