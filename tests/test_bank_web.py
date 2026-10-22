"""Web tests for /bank (Part C of bank-statement-import).

The service layer (app.domain.bank.service / accounts, built in Part B) is replaced by a small
in-memory fake with the signatures of the spec, so these tests exercise routing, forms,
templates, error messages and plain language only. Parsers, dedupe keys and storage are the real
Part A code. Domain behaviour is tested in tests/bank.
"""

from datetime import date, datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from app.domain.bank import accounts as bank_accounts
from app.domain.bank import service as bank_service
from app.domain.bank.dedupe import compute_keys
from app.domain.bank.iban import is_valid_iban, normalize_iban
from app.domain.bank.parsers import BANK_LABELS, FORMAT_LABELS, format_description, parse_statement
from app.domain.bank.storage import BankFileStorage, storage_ext
from app.domain.bank.types import (
    ACCOUNT_IN_USE,
    BAD_IBAN,
    WRONG_ACCOUNT,
    BankImportError,
    ImportPreview,
    ImportResult,
    PreviewRow,
)
from app.domain.glossary import GLOSSARY
from app.web import bank_routes
from tests.web_helpers import assert_plain_language, bare_term_elements, missing_term_keys

FIXTURES = Path(__file__).parent / "bank" / "parsers" / "fixtures"
ABN_IBAN = "NL91ABNA0417164300"
BAD_IBAN_MESSAGE = (
    "Dit IBAN-nummer klopt niet. Controleer of je alle tekens hebt overgenomen "
    "(bijvoorbeeld NL91 ABNA 0417 1643 00)."
)
NEW_TERMS = (
    "bankrekening", "bankafschrift", "camt053", "mt940", "csv_export",
    "bijschrijving_afschrijving", "dubbele_transactie", "transactie",
)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeBank:
    """In-memory stand-in for Part B (accounts + service) with the spec's signatures."""

    def __init__(self, asset_account_id: int, storage: BankFileStorage):
        self.asset_account_id = asset_account_id
        self.storage = storage
        self.ids = count(1)
        self.accounts: list[SimpleNamespace] = []
        self.batches: dict[int, SimpleNamespace] = {}
        self.transactions: list[SimpleNamespace] = []
        self.per_page = 50

    # --- accounts
    def suggest_account(self, session):
        taken = {a.account_id for a in self.accounts}
        return None if self.asset_account_id in taken else SimpleNamespace(id=self.asset_account_id)

    def list_bank_accounts(self, session):
        return list(self.accounts)

    def create_bank_account(self, session, name, iban, account_id, bank=None):
        if not is_valid_iban(normalize_iban(iban)):
            raise BankImportError(BAD_IBAN, BAD_IBAN_MESSAGE)
        for a in self.accounts:
            if a.account_id == account_id:
                raise BankImportError(
                    ACCOUNT_IN_USE,
                    f"Deze grootboekrekening hoort al bij {a.name}. Kies een andere rekening of gebruik die bankrekening.",
                )
        a = SimpleNamespace(
            id=next(self.ids), name=name, iban=normalize_iban(iban), bank=bank, account_id=account_id,
            journal_id=1, is_active=True,
        )
        self.accounts.append(a)
        return a

    def update_bank_account(self, session, bank_account_id, **fields):
        a = self.get_account(bank_account_id)
        self.last_update = fields
        for key in ("name", "bank", "iban", "account_id"):
            if fields.get(key) is not None:
                setattr(a, key, fields[key])
        return a

    def deactivate(self, session, bank_account_id):
        self.get_account(bank_account_id).is_active = False

    def get_account(self, bank_account_id):
        return next((a for a in self.accounts if a.id == bank_account_id), None)

    def has_imports(self, session, bank_account_id):
        return any(b.bank_account_id == bank_account_id and b.status == "afgerond" for b in self.batches.values())

    # --- service
    def _classify(self, batch):
        content = self.storage.open(batch.sha256, batch.ext).read()
        statement = parse_statement(content)
        keys = compute_keys(batch.bank_account_id, statement)
        stored = {(t.dedupe_key, t.occurrence) for t in self.transactions if t.bank_account_id == batch.bank_account_id}
        loose = {
            (t.booking_date, t.amount_cents, t.counterparty_iban)
            for t in self.transactions if t.bank_account_id == batch.bank_account_id
        }
        new, existing, maybe = [], [], []
        for i, (tx, (key, occ)) in enumerate(zip(statement.transactions, keys)):
            row = PreviewRow(i, tx, key, occ)
            if (key, occ) in stored:
                existing.append(row)
            elif (tx.booking_date, tx.amount_cents, tx.counterparty_iban) in loose:
                maybe.append(row)
            else:
                new.append(row)
        dates = [t.booking_date for t in statement.transactions]
        done = next(
            (b for b in self.batches.values()
             if b is not batch and b.status == "afgerond" and b.sha256 == batch.sha256
             and b.bank_account_id == batch.bank_account_id),
            None,
        )
        return statement, ImportPreview(
            batch_id=batch.id, bank_account_id=batch.bank_account_id, original_filename=batch.original_filename,
            sha256=batch.sha256, format_label=FORMAT_LABELS[statement.format],
            bank_label=BANK_LABELS.get(statement.bank or ""), period_start=min(dates), period_end=max(dates),
            new_rows=tuple(new), existing_rows=tuple(existing), maybe_rows=tuple(maybe),
            warnings=(
                () if statement.account_iban
                else ("In dit bestand staat geen rekeningnummer; controleer of dit de juiste bankrekening is.",)
            ),
            already_imported_on=done.confirmed_at if done else None,
        )

    def start_import(self, session, storage, bank_account_id, filename, content):
        account = self.get_account(bank_account_id)
        if account is None or not account.is_active:
            raise BankImportError("NOT_ACTIVE", "Deze bankrekening staat uit. Zet hem eerst weer aan.")
        statement = parse_statement(content, account.bank)
        if statement.account_iban and statement.account_iban != account.iban:
            raise BankImportError(
                WRONG_ACCOUNT,
                f"Dit afschrift hoort bij {statement.account_iban}, maar je koos {account.name} ({account.iban}). "
                "Kies de juiste bankrekening.",
            )
        ext = storage_ext(statement.format, filename)
        stored = storage.write(content, ext)
        batch = SimpleNamespace(
            id=next(self.ids), bank_account_id=bank_account_id, status="voorbeeld", original_filename=filename,
            sha256=stored.sha256, ext=ext, size=stored.size, detected_format=statement.format,
            detected_bank=statement.bank, period_start=None, period_end=None, new_count=0, skipped_count=0,
            maybe_duplicate_count=0, created_at=datetime.now(), confirmed_at=None,
        )
        self.batches[batch.id] = batch
        return self._classify(batch)[1]

    def preview_batch(self, session, storage, batch_id):
        return self._classify(self.batches[batch_id])[1]

    def confirm_import(self, session, storage, batch_id, include_maybe_ids):
        batch = self.batches[batch_id]
        if batch.status == "afgerond":
            return ImportResult(batch_id, batch.new_count, batch.skipped_count, batch.maybe_duplicate_count, True)
        statement, preview = self._classify(batch)
        take = list(preview.new_rows) + [r for r in preview.maybe_rows if r.index in include_maybe_ids]
        for row in take:
            t = row.transaction
            self.transactions.append(SimpleNamespace(
                id=next(self.ids), bank_account_id=batch.bank_account_id, import_batch_id=batch.id,
                booking_date=t.booking_date, amount_cents=t.amount_cents, counterparty_name=t.counterparty_name,
                counterparty_iban=t.counterparty_iban, description=t.description,
                balance_after_cents=t.balance_after_cents, dedupe_key=row.dedupe_key, occurrence=row.occurrence,
            ))
        batch.status, batch.confirmed_at = "afgerond", datetime.now()
        batch.new_count, batch.skipped_count = len(take), preview.existing_count
        batch.maybe_duplicate_count = preview.maybe_count - len([r for r in preview.maybe_rows if r.index in include_maybe_ids])
        batch.period_start, batch.period_end = preview.period_start, preview.period_end
        return ImportResult(batch_id, batch.new_count, batch.skipped_count, batch.maybe_duplicate_count)

    def _page(self, rows, page):
        start = (max(page, 1) - 1) * self.per_page
        return SimpleNamespace(items=rows[start:start + self.per_page], page=max(page, 1), per_page=self.per_page, total=len(rows))

    def list_transactions(self, session, q=None, bank_account_id=None, batch_id=None, page=1):
        rows = [
            t for t in self.transactions
            if (bank_account_id is None or t.bank_account_id == bank_account_id)
            and (batch_id is None or t.import_batch_id == batch_id)
            and (not q or q.casefold() in f"{t.counterparty_name} {t.description} {t.counterparty_iban}".casefold())
        ]
        rows.sort(key=lambda t: (t.booking_date, t.id), reverse=True)
        return self._page(rows, page)

    def list_batches(self, session, page=1):
        rows = sorted((b for b in self.batches.values() if b.status == "afgerond"), key=lambda b: b.id, reverse=True)
        return self._page(rows, page)

    def bank_stats(self, session):
        done = [b.confirmed_at for b in self.batches.values() if b.status == "afgerond"]
        return SimpleNamespace(
            account_count=len(self.accounts), transaction_count=len(self.transactions),
            last_imported_at=max(done) if done else None,
        )


@pytest.fixture
def bank(client, monkeypatch, tmp_path):
    with client.app.state.engine.connect() as conn:
        asset_id = conn.execute(text("SELECT id FROM account WHERE code = '1210'")).scalar()
    storage = BankFileStorage(tmp_path / "bank")
    fake = FakeBank(asset_id, storage)
    client.app.dependency_overrides[bank_routes.get_storage] = lambda: storage
    for module, names in (
        (bank_accounts, ("suggest_account", "list_bank_accounts", "create_bank_account", "update_bank_account", "deactivate")),
        (bank_service, ("start_import", "preview_batch", "confirm_import", "list_transactions", "list_batches", "bank_stats")),
    ):
        for name in names:
            monkeypatch.setattr(module, name, getattr(fake, name), raising=False)
    monkeypatch.setattr(bank_routes, "_get_bank_account", lambda session, i: fake.get_account(i))
    monkeypatch.setattr(bank_routes, "_get_batch", lambda session, i: fake.batches.get(i))
    monkeypatch.setattr(bank_routes, "_has_imports", lambda session, i: fake.has_imports(session, i))
    yield fake
    client.app.dependency_overrides.clear()


def add_account(client, **over):
    data = {"name": "Zakelijke rekening ABN", "iban": ABN_IBAN, "bank": "abn_amro", "account_id": "0"}
    data.update(over)
    return client.post("/bank/rekeningen/nieuw", data=data, follow_redirects=False)


@pytest.fixture
def account(client, bank):
    r = add_account(client, account_id=str(bank.asset_account_id))
    assert r.status_code == 303
    return bank.accounts[0]


def upload(client, account, name="afschrift.xml", content=None, **over):
    content = fixture("camt053_002.xml") if content is None else content
    data = {"bank_account_id": str(account.id), **over}
    return client.post("/bank/importeren", data=data, files={"file": (name, content, "application/octet-stream")},
                       follow_redirects=False)


def import_file(client, account, name="camt053_002.xml", include=()):
    r = upload(client, account, name, fixture(name))
    assert r.status_code == 303, r.text
    batch_url = r.headers["location"]
    c = client.post(batch_url + "/bevestigen", data={"include_maybe": [str(i) for i in include]}, follow_redirects=False)
    assert c.status_code == 303
    return batch_url


# --- overview -----------------------------------------------------------------


def test_bank_is_no_longer_a_placeholder(client, bank):
    html = client.get("/bank").text
    assert "Deze pagina is nog in ontwikkeling" not in html
    assert 'data-term="bank"' in html


def test_empty_state_without_bank_account(client, bank):
    html = client.get("/bank").text
    assert "Voeg eerst je bankrekening toe" in html
    assert 'href="/bank/rekeningen/nieuw"' in html
    assert "Afschrift importeren" not in html


def test_populated_overview_has_stat_cards_account_card_and_tabs(client, bank, account):
    import_file(client, account)
    html = client.get("/bank").text
    for label in ("Aantal bankrekeningen", "Transacties", "Laatst geïmporteerd"):
        assert label in html
    assert "Afschrift importeren" in html and f"/bank/importeren?rekening={account.id}" in html
    assert "Importgeschiedenis" in html
    assert "NL91 ABNA 0417 1643 00" in html


def test_transactions_list_sorted_with_in_and_out_amounts(client, bank, account):
    import_file(client, account)
    html = client.get("/bank").text
    assert "Kantoor BV" in html and "Klant BV" in html
    assert "amount--in" in html and "amount--out" in html
    assert "+€ 1.000,00" in html and "-€ 12,10" in html
    assert html.index("04-03-2024") < html.index("01-03-2024")  # newest first


def test_transactions_search_filter_and_partial(client, bank, account):
    import_file(client, account)
    hit = client.get("/bank/transacties", params={"q": "Klant BV"}).text
    assert "Klant BV" in hit and "Kantoor BV" not in hit
    assert "<html" not in hit  # htmx partial
    miss = client.get("/bank", params={"q": "bestaatniet"}).text
    assert "Geen transacties gevonden" in miss
    assert "Kantoor BV" in client.get("/bank", params={"rekening": account.id}).text


def test_transactions_pagination(client, bank, account):
    import_file(client, account)
    bank.per_page = 2
    html = client.get("/bank").text
    assert "Toont 1-2 van" in html and 'aria-label="Paginering"' in html
    assert "Toont 3-4 van" in client.get("/bank", params={"page": 2}).text


def test_transactions_are_read_only(client, bank, account):
    import_file(client, account)
    html = client.get("/bank").text
    for word in ("Verwijderen", "Wijzigen"):
        assert word not in html
    assert '<form method="post"' not in html


def test_transactions_filtered_by_import(client, bank, account):
    batch_url = import_file(client, account)
    batch_id = batch_url.rsplit("/", 1)[1]
    html = client.get("/bank", params={"importeren": batch_id}).text
    assert "alleen de transacties van één import" in html and "Kantoor BV" in html


def test_import_history_tab(client, bank, account):
    batch_url = import_file(client, account, "camt053_002.xml")
    html = client.get("/bank?tab=geschiedenis").text
    assert "camt053_002.xml" in html
    assert "CAMT.053-bestand van ABN AMRO" in html
    assert f"{batch_url}/bestand" in html and "Origineel bestand downloaden" in html
    assert "01-03-2024 t/m 04-03-2024" in html


def test_history_empty(client, bank, account):
    assert "Nog niets geïmporteerd" in client.get("/bank?tab=geschiedenis").text


# --- bankrekening forms ---------------------------------------------------------


def test_new_account_form_offers_defaults(client, bank):
    html = client.get("/bank/rekeningen/nieuw").text
    assert "Zakelijke rekening" in html
    assert f'<option value="{bank.asset_account_id}" selected>1210' in html
    assert "maakt zelf de map voor de bijbehorende bankboekingen aan" in html
    assert 'data-term="bankdagboek"' in html


def test_new_account_form_prefills_name_from_bank(client, bank):
    assert 'value="Zakelijke rekening ING"' in client.get("/bank/rekeningen/nieuw?bank=ing").text


def test_create_account(client, bank):
    r = add_account(client, account_id=str(bank.asset_account_id), iban="nl91 abna 0417 1643 00")
    assert r.status_code == 303 and r.headers["location"] == "/bank?melding=rekening_toegevoegd"
    assert bank.accounts[0].iban == ABN_IBAN
    assert "De bankrekening is toegevoegd" in client.get(r.headers["location"]).text


def test_create_account_without_name_gets_default(client, bank):
    add_account(client, name="", bank="ing", account_id=str(bank.asset_account_id))
    assert bank.accounts[0].name == "Zakelijke rekening ING"


def test_invalid_iban_is_refused_in_plain_dutch_and_values_are_kept(client, bank):
    r = add_account(client, iban="NL00 FOUT", account_id=str(bank.asset_account_id), name="Mijn rekening")
    assert r.status_code == 422
    assert BAD_IBAN_MESSAGE in r.text
    assert 'role="alert"' in r.text and 'value="Mijn rekening"' in r.text and "NL00 FOUT" in r.text


def test_account_already_linked_is_refused_and_disabled_in_the_form(client, bank, account):
    r = add_account(client, iban="NL20INGB0001234567", account_id=str(bank.asset_account_id))
    assert r.status_code == 422
    assert "Deze grootboekrekening hoort al bij Zakelijke rekening ABN." in r.text
    form = client.get("/bank/rekeningen/nieuw").text
    assert "(al in gebruik bij Zakelijke rekening ABN)" in form


def test_missing_grootboekrekening_is_a_plain_error(client, bank):
    r = client.post("/bank/rekeningen/nieuw", data={"name": "x", "iban": ABN_IBAN})
    assert r.status_code == 422 and "Kies bij welke grootboekrekening" in r.text


def test_edit_account_renames(client, bank, account):
    r = client.post(f"/bank/rekeningen/{account.id}/bewerken",
                    data={"name": "Nieuwe naam", "iban": ABN_IBAN, "bank": "abn_amro", "account_id": str(account.account_id)},
                    follow_redirects=False)
    assert r.status_code == 303 and account.name == "Nieuwe naam"
    assert bank.last_update["iban"] == ABN_IBAN  # no imports yet: the fields may change


def test_edit_account_with_imports_locks_iban_and_account(client, bank, account):
    import_file(client, account)
    html = client.get(f"/bank/rekeningen/{account.id}/bewerken").text
    assert html.count(" disabled") >= 2
    assert "omdat er al afschriften van zijn ingelezen" in html
    client.post(f"/bank/rekeningen/{account.id}/bewerken", data={"name": "Andere naam", "bank": ""})
    assert bank.last_update["iban"] is None and bank.last_update["account_id"] is None
    assert account.name == "Andere naam"


def test_deactivate_account_refuses_new_imports(client, bank, account):
    r = client.post(f"/bank/rekeningen/{account.id}/bewerken", data={"actie": "deactiveren"}, follow_redirects=False)
    assert r.status_code == 303 and not account.is_active
    assert "Niet actief" in client.get("/bank").text
    assert f"/bank/importeren?rekening={account.id}" not in client.get("/bank").text
    assert upload(client, account).status_code == 422


def test_edit_unknown_account_is_404(client, bank):
    assert client.get("/bank/rekeningen/99/bewerken").status_code == 404
    assert client.post("/bank/rekeningen/99/bewerken", data={}).status_code == 404


# --- import flow ----------------------------------------------------------------


def test_upload_form_lists_formats_with_explanations(client, bank, account):
    html = client.get(f"/bank/importeren?rekening={account.id}").text
    for key in ("camt053", "mt940", "csv_export", "bewaarplicht"):
        assert f'data-term="{key}"' in html
    assert f'value="{account.id}" selected' in html
    assert 'enctype="multipart/form-data"' in html


def test_upload_form_without_account_points_to_adding_one(client, bank):
    assert "Voeg eerst je bankrekening toe" in client.get("/bank/importeren").text


@pytest.mark.parametrize(
    ("name", "found", "label"),
    [
        ("camt053_002.xml", "7 transacties", "CAMT.053-bestand van ABN AMRO"),
        ("mt940_ing.sta", "5 transacties", "MT940-bestand van ING"),
        ("ing.csv", "4 transacties", "CSV-export van ING"),
    ],
)
def test_happy_path_upload_preview_confirm_result(client, bank, name, found, label):
    statement = parse_statement(fixture(name))
    add_account(client, iban=statement.account_iban, account_id=str(bank.asset_account_id), bank=statement.bank)
    account = bank.accounts[0]
    r = upload(client, account, name, fixture(name))
    assert r.status_code == 303
    preview_url = r.headers["location"]
    assert preview_url.startswith("/bank/importeren/")
    assert bank.transactions == []  # step 1 inserts nothing

    page = client.get(preview_url)
    assert page.status_code == 200
    assert f"Gevonden: <strong>{found}</strong>" in page.text
    assert f"{len(statement.transactions)} nieuw" in page.text
    assert label.split(" van ")[0] in page.text
    assert 'data-term="' + {"camt053": "camt053", "mt940": "mt940", "csv": "csv_export"}[statement.format] + '"' in page.text
    assert f'action="{preview_url}/bevestigen"' in page.text
    assert "disabled" not in page.text.split("form-actions")[1].split("</div>")[0]

    done = client.post(preview_url + "/bevestigen", follow_redirects=False)
    assert done.status_code == 303 and done.headers["location"] == preview_url
    assert len(bank.transactions) == len(statement.transactions)
    result = client.get(preview_url).text
    assert f"{len(statement.transactions)} transacties geïmporteerd" in result
    assert f"/bank?importeren={preview_url.rsplit('/', 1)[1]}" in result


def test_preview_shows_accounts_and_period(client, bank, account):
    r = upload(client, account)
    html = client.get(r.headers["location"]).text
    assert "Zakelijke rekening ABN" in html and "01-03-2024 tot en met 04-03-2024" in html
    assert "Er is nog niets opgeslagen" in html


def test_preview_warning_when_file_has_no_account_number(client, bank, monkeypatch, account):
    r = upload(client, account)
    original = bank._classify

    def without_iban(batch):
        statement, preview = original(batch)
        return statement, preview.__class__(**{**preview.__dict__, "warnings": (
            "In dit bestand staat geen rekeningnummer; controleer of dit de juiste bankrekening is.",)})

    monkeypatch.setattr(bank, "_classify", without_iban)
    html = client.get(r.headers["location"]).text
    assert "In dit bestand staat geen rekeningnummer" in html and "notice--warning" in html


def test_same_file_again_is_flagged_and_confirm_disabled(client, bank, account):
    import_file(client, account)
    r = upload(client, account)
    html = client.get(r.headers["location"]).text
    assert "Dit bestand heb je al geïmporteerd op" in html and "Er is niets nieuws." in html
    assert "<button type=\"submit\" class=\"btn\" disabled>" in html.replace("\n", "")  # confirm is disabled


def test_overlapping_statement_only_imports_new_rows(client, bank, account):
    import_file(client, account, "camt053_002.xml")
    before = len(bank.transactions)
    # byte-identical content is the same file; make a different file with the same transactions
    modified = fixture("camt053_002.xml") + b"\n<!-- opnieuw gedownload -->"
    r = upload(client, account, "opnieuw.xml", modified)
    html = client.get(r.headers["location"]).text
    assert "0 nieuw" in html and "al eerder geïmporteerd" in html and "Al eerder geïmporteerd: 7" in html
    client.post(r.headers["location"] + "/bevestigen")
    assert len(bank.transactions) == before


def test_maybe_duplicates_are_listed_with_opt_in_checkbox(client, bank, account):
    import_file(client, account, "camt053_002.xml")
    # Same date/amount/counterparty, other description: only fuzzy matches remain.
    changed = fixture("camt053_002.xml")
    for t in bank.transactions:
        t.dedupe_key = "andere-sleutel-" + t.dedupe_key
    r = upload(client, account, "ander.xml", changed + b"\n<!-- v2 -->")
    html = client.get(r.headers["location"]).text
    assert "Mogelijk dubbel: 7" in html
    assert html.count('name="include_maybe"') == 7
    assert 'data-term="dubbele_transactie"' in html
    before = len(bank.transactions)
    client.post(r.headers["location"] + "/bevestigen", data={"include_maybe": ["0", "1"]})
    assert len(bank.transactions) == before + 2
    result = client.get(r.headers["location"]).text
    assert "2 transacties geïmporteerd" in result and "5 mogelijk dubbel overgeslagen" in result


def test_confirm_twice_is_idempotent_with_notice(client, bank, account):
    batch_url = import_file(client, account)
    count_before = len(bank.transactions)
    again = client.post(batch_url + "/bevestigen", follow_redirects=False)
    assert again.status_code == 303 and again.headers["location"] == batch_url + "?melding=al_verwerkt"
    assert len(bank.transactions) == count_before
    assert "Deze import is al verwerkt." in client.get(again.headers["location"]).text


def test_confirm_integrity_error_maps_to_already_processed(client, bank, account, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    r = upload(client, account)

    def boom(*a, **k):
        raise IntegrityError("insert", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(bank_service, "confirm_import", boom)
    c = client.post(r.headers["location"] + "/bevestigen", follow_redirects=False)
    assert c.status_code == 303 and c.headers["location"].endswith("?melding=al_verwerkt")


def test_wrong_iban_is_refused_with_plain_message(client, bank, account):
    r = upload(client, account, "ing.sta", fixture("mt940_ing.sta"))
    assert r.status_code == 422
    assert "Dit afschrift hoort bij NL20INGB0001234567, maar je koos Zakelijke rekening ABN" in r.text
    assert "Kies de juiste bankrekening." in r.text
    assert bank.batches == {} or all(b.status == "voorbeeld" for b in bank.batches.values())


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        (b"<html><body>geen bankbestand</body></html>", "herkennen"),
        (b"", "Er staat niets in dit bestand"),
        (b"%PDF-1.4\n%%EOF\n", "Dit is een PDF"),
    ],
)
def test_unreadable_files_give_plain_errors(client, bank, account, content, expected):
    r = upload(client, account, "rommel.txt", content)
    assert r.status_code == 422
    assert 'role="alert"' in r.text
    assert "Traceback" not in r.text and "BankImportError" not in r.text and "PARSE_ERROR" not in r.text
    assert missing_term_keys(r.text) == []


def test_empty_statement_is_refused(client, bank, account):
    empty = b'<?xml version="1.0"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt></BkToCstmrStmt></Document>'
    r = upload(client, account, "leeg.xml", empty)
    assert r.status_code == 422 and 'role="alert"' in r.text


def test_upload_without_file_or_account(client, bank, account):
    r = client.post("/bank/importeren", data={"bank_account_id": str(account.id)})
    assert r.status_code == 422 and "Je hebt nog geen bestand gekozen" in r.text
    r = client.post("/bank/importeren", files={"file": ("a.csv", b"x", "text/csv")})
    assert r.status_code == 422 and "Kies eerst bij welke bankrekening" in r.text
    assert f'<option value="{account.id}"' in r.text  # form stays usable


def test_too_big_file_is_refused_in_plain_dutch(client, bank, account, monkeypatch):
    import app.domain.bank.parsers as parsers

    monkeypatch.setattr(bank_routes, "MAX_FILE_BYTES", 100)
    monkeypatch.setattr(parsers, "MAX_FILE_BYTES", 100)
    r = upload(client, account, "groot.csv", b"x" * 500)
    assert r.status_code == 422 and "10 MB" in r.text


def test_storage_failure_gives_500_with_plain_message(client, bank, account, monkeypatch):
    from app.domain.errors import DocumentStorageFailedError

    def fail(*a, **k):
        raise DocumentStorageFailedError("Het bankbestand kon niet worden opgeslagen. Probeer het opnieuw.")

    monkeypatch.setattr(bank_service, "start_import", fail)
    r = upload(client, account)
    assert r.status_code == 500 and "kon niet worden opgeslagen" in r.text


def test_unknown_batch_is_404(client, bank):
    for url in ("/bank/importeren/99", "/bank/importeren/99/bestand"):
        assert client.get(url).status_code == 404
    assert client.post("/bank/importeren/99/bevestigen").status_code == 404


def test_original_file_download_returns_identical_bytes(client, bank, account):
    batch_url = import_file(client, account)
    r = client.get(batch_url + "/bestand")
    assert r.status_code == 200
    assert r.content == fixture("camt053_002.xml")
    assert "attachment" in r.headers["content-disposition"] and "camt053_002.xml" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_missing_original_file_is_a_plain_error(client, bank, account):
    batch_url = import_file(client, account)
    batch = bank.batches[int(batch_url.rsplit("/", 1)[1])]
    path = bank.storage.path_for(batch.sha256, batch.ext)
    path.chmod(0o644)
    path.unlink()
    r = client.get(batch_url + "/bestand")
    assert r.status_code == 500 and "Herstel data/bank" in r.text


# --- plain language -----------------------------------------------------------


def test_new_terms_are_in_the_glossary_with_plain_phrases():
    expected = {
        "bankrekening": "Je rekening bij de bank",
        "bankafschrift": "Overzicht van bij- en afschrijvingen",
        "camt053": "Bankbestand (XML)",
        "mt940": "Bankbestand (oud formaat)",
        "csv_export": "Bankbestand voor Excel",
        "bijschrijving_afschrijving": "Geld erbij / geld eraf",
        "dubbele_transactie": "Staat er al",
        "transactie": "Een bij- of afschrijving",
    }
    assert set(expected) == set(NEW_TERMS)
    for key, plain in expected.items():
        assert GLOSSARY[key].plain == plain
        assert 0 < len(GLOSSARY[key].explanation) <= 220


def test_every_bank_screen_is_plain_language(client, bank, account):
    batch_url = import_file(client, account)
    second = upload(client, account).headers["location"]  # same file again: confirm disabled
    for url in (
        "/bank", "/bank?tab=geschiedenis", "/bank/rekeningen/nieuw", f"/bank/rekeningen/{account.id}/bewerken",
        "/bank/importeren", f"/bank/importeren?rekening={account.id}", batch_url, second,
    ):
        assert_plain_language(client, url)


def test_error_screens_are_plain_language(client, bank, account):
    for response in (
        add_account(client, iban="NL00", account_id=str(bank.asset_account_id)),
        upload(client, account, "ing.sta", fixture("mt940_ing.sta")),
        upload(client, account, "x.csv", b"a;b\n1;2\n"),
    ):
        assert response.status_code == 422
        assert missing_term_keys(response.text) == []
        assert bare_term_elements(response.text) == []


def test_new_terms_have_info_icons_where_shown(client, bank, account):
    import_file(client, account)
    pages = client.get("/bank").text + client.get("/bank?tab=geschiedenis").text
    for key in ("transactie", "bijschrijving_afschrijving", "dubbele_transactie", "bankafschrift", "bewaarplicht", "iban"):
        assert f'data-term="{key}"' in pages, key
    assert 'data-term="bankrekening"' in client.get("/bank/rekeningen/nieuw").text


def test_bank_nav_item_is_active_on_subpages(client, bank, account):
    html = client.get("/bank/rekeningen/nieuw").text
    assert 'aria-current="page"' in html.split("<main")[0]


def test_summary_helper_matches_format_description():
    st = parse_statement(fixture("camt053_002.xml"))
    assert format_description(st) == "CAMT.053-bestand van ABN AMRO"
    assert date(2024, 3, 1) == st.transactions[0].booking_date
