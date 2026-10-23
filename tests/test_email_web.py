"""Web tests for the e-mail intake UI (Part B). Uses fake runner/settings; no Part A needed."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.domain.glossary import GLOSSARY
from app.web import email_routes
from app.web.navigation import SETTINGS_NAV
from tests.web_helpers import assert_plain_language, visible_text

SECRET = "geheim-wachtwoord-123"


class FakeError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


class SettingsProxy:
    """The real settings plus imap_* values (works with or without Part A's fields)."""

    def __init__(self, real, **over):
        self._real, self._over = real, over

    def __getattr__(self, name):
        if name in self._over:
            return self._over[name]
        return getattr(self._real, name)


def report(**kw):
    base = dict(
        status="klaar", mails_seen=2, mails_processed=2, documents_new=3, documents_duplicate=1,
        attachments_skipped=0, mails_without_attachments=0, mails_failed=0, problems=[],
        started_at=datetime(2026, 1, 1, 10, 0), finished_at=datetime(2026, 1, 1, 10, 1),
    )
    base.update(kw)
    return SimpleNamespace(**base)


class FakeRunner:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, 0
        self.last_report = None

    def run_now(self):
        self.calls += 1
        if self.error:
            raise self.error
        self.last_report = self.result
        return self.result


@pytest.fixture(autouse=True)
def fake_error_class(monkeypatch):
    # Part A's EmailIntakeError may not exist yet; the tests raise this stand-in.
    monkeypatch.setattr(email_routes, "EmailIntakeError", FakeError)


def configure(client, configured=True, runner=None, **over):
    values = dict(
        imap_configured=configured, imap_host="imap.example.com", imap_port=993,
        imap_user="facturen@example.com",
        imap_password=SimpleNamespace(get_secret_value=lambda: SECRET) if configured else None,
        imap_folder="INBOX", imap_processed_folder="Verwerkt", imap_poll_interval_minutes=0,
    )
    values.update(over)
    client.app.state.settings = SettingsProxy(client.app.state.settings, **values)
    client.app.state.email_runner = runner or FakeRunner(report())
    return client.app.state.email_runner


def test_glossary_terms_present():
    for key in ("factuurmailbox", "imap", "app_wachtwoord"):
        assert len(GLOSSARY[key].explanation) <= 220


def test_settings_nav_has_koppelingen_group():
    group = SETTINGS_NAV[-1]
    assert group.label == "Koppelingen"
    assert [(i.label, i.path, i.term_key) for i in group.items] == [
        ("E-mail", "/instellingen/email", "factuurmailbox")
    ]


def test_inbox_button_shown_when_configured(client):
    configure(client)
    html = client.get("/inbox").text
    assert 'action="/inbox/ophalen"' in html
    assert "Nu ophalen" in html
    assert "Haalt facturen op uit je factuurmailbox." in html
    assert "E-mail koppelen" not in html


def test_inbox_link_when_not_configured(client):
    configure(client, configured=False)
    html = client.get("/inbox").text
    assert 'action="/inbox/ophalen"' not in html
    assert 'href="/instellingen/email"' in html
    assert "E-mail koppelen" in html


def test_inbox_without_runner_still_works(client):
    html = client.get("/inbox").text
    assert "Bestand toevoegen" in html


def test_ophalen_redirects_and_notice(client):
    runner = configure(client)
    r = client.post("/inbox/ophalen", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/inbox?melding=opgehaald"
    assert runner.calls == 1
    text = visible_text(client.get("/inbox?melding=opgehaald").text)
    assert "Klaar: 3 nieuwe documenten uit je mailbox gehaald, 1 stond er al." in text
    assert "alleen als het programma draait" in text


def test_notice_nothing_new(client):
    configure(client, runner=FakeRunner(report(documents_new=0, documents_duplicate=0)))
    client.post("/inbox/ophalen")
    text = visible_text(client.get("/inbox?melding=opgehaald").text)
    assert "Geen nieuwe mail met facturen gevonden." in text


def test_notice_problems_and_no_attachment(client):
    problems = ["De mail 'Factuur 123' kon niet worden opgeslagen; hij staat nog in je mailbox."]
    configure(client, runner=FakeRunner(report(
        problems=problems, mails_without_attachments=1, documents_new=1, documents_duplicate=0)))
    client.post("/inbox/ophalen")
    text = visible_text(client.get("/inbox?melding=opgehaald").text)
    assert "Klaar: 1 nieuw document uit je mailbox gehaald." in text
    assert "De mail 'Factuur 123' kon niet worden opgeslagen" in text
    assert "1 mail zonder PDF of foto is overgeslagen" in text


def test_busy_message(client):
    configure(client, runner=FakeRunner(SimpleNamespace(status="bezig")))
    r = client.post("/inbox/ophalen", follow_redirects=False)
    assert r.status_code == 303
    text = visible_text(client.get(r.headers["location"]).text)
    assert "Er wordt al opgehaald. Wacht even en ververs de pagina." in text


def test_error_shown_with_settings_link(client):
    err = FakeError("EMAIL_LOGIN_FAILED", "Inloggen bij de mailbox is mislukt. Controleer gebruikersnaam.")
    configure(client, runner=FakeRunner(error=err))
    r = client.post("/inbox/ophalen", follow_redirects=False)
    assert r.status_code == 303
    html = client.get(r.headers["location"]).text
    assert "Inloggen bij de mailbox is mislukt." in html
    assert 'role="alert"' in html
    assert 'href="/instellingen/email"' in html
    # shown once: not on a plain reload of the inbox
    assert "Inloggen bij de mailbox is mislukt." not in client.get("/inbox").text


def test_ophalen_unconfigured_redirects_with_error(client):
    configure(client, configured=False)
    r = client.post("/inbox/ophalen", follow_redirects=False)
    assert r.status_code == 303
    html = client.get(r.headers["location"]).text
    assert "De mailbox is nog niet gekoppeld." in html


def test_ophalen_cross_site_blocked(client):
    configure(client)
    r = client.post("/inbox/ophalen", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_settings_page_configured_hides_password(client):
    configure(client, imap_poll_interval_minutes=15)
    html = client.get("/instellingen/email").text
    assert "Je factuurmailbox" in visible_text(html)
    assert "imap.example.com" in html and "facturen@example.com" in html
    assert "Wachtwoord: ingesteld" in html
    assert SECRET not in html
    assert "Automatisch ophalen: elke 15 minuten" in html
    assert "alleen als het programma draait" in html
    assert "Verbinding testen" in html
    assert "IMAP_HOST" in html and "IMAP_PASSWORD" in html


def test_settings_page_unconfigured(client):
    configure(client, configured=False)
    html = client.get("/instellingen/email").text
    assert "Wachtwoord: niet ingesteld" in html
    assert "Uit; gebruik de knop Nu ophalen in de Inbox" in html
    assert "nog niet gekoppeld" in html


def test_settings_page_lists_recent_messages(client, monkeypatch):
    configure(client)

    def row(day, frm, subject, outcome, new, dup, moved=True):
        return SimpleNamespace(
            received_at=datetime(2026, 2, day, 9, 0), from_addr=frm, subject=subject,
            outcome=outcome, documents_new=new, documents_duplicate=dup, moved=moved)

    rows = [
        row(4, "a@x.nl", "Factuur 1", "opgeslagen", 3, 0),
        row(3, "b@x.nl", "Dubbel", "alleen_dubbel", 0, 1),
        row(2, "c@x.nl", "Praatje", "geen_bijlage", 0, 0),
        row(1, "d@x.nl", "Vast", "opgeslagen", 1, 0, moved=False),
    ]
    monkeypatch.setattr(email_routes, "recent_messages", lambda session, limit=10: rows)
    html = client.get("/instellingen/email").text
    for s in ("Factuur 1", "3 nieuw", "al aanwezig", "geen bijlage", "nog niet verplaatst", "d@x.nl"):
        assert s in html


def test_settings_page_shows_last_run(client):
    runner = configure(client)
    runner.last_report = report(problems=["Mail X mislukt"])
    html = client.get("/instellingen/email").text
    assert "Mail X mislukt" in html
    assert "3 nieuwe documenten" in html


def test_connection_ok(client, monkeypatch):
    configure(client)
    monkeypatch.setattr(
        email_routes, "test_connection",
        lambda settings: SimpleNamespace(unread_count=4, folder="INBOX"),
    )
    r = client.post("/instellingen/email/test")
    assert r.status_code == 200
    assert "Verbinding gelukt: er staan 4 ongelezen mails in INBOX." in r.text


def test_connection_error(client, monkeypatch):
    configure(client)

    def boom(settings):
        raise FakeError("EMAIL_CONNECT_FAILED", "Er kon geen verbinding worden gemaakt met imap.example.com.")

    monkeypatch.setattr(email_routes, "test_connection", boom)
    r = client.post("/instellingen/email/test")
    assert r.status_code == 200
    assert "Er kon geen verbinding worden gemaakt met imap.example.com." in r.text
    assert SECRET not in r.text


@pytest.mark.parametrize("configured", [True, False])
def test_plain_language(client, configured):
    configure(client, configured=configured)
    assert_plain_language(client, "/instellingen/email")
    assert_plain_language(client, "/inbox")
