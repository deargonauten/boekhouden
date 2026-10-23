import logging
import threading

from app.config import Settings
from app.domain.email_intake import Busy, EmailLoginFailedError, EmailNotConfiguredError, IntakeReport, IntakeRunner
from tests.email_intake.conftest import PDF, FakeMailbox, make_mail, raw


def runner(test_settings, session_factory, box_or_factory):
    factory = box_or_factory if callable(box_or_factory) else (lambda s: box_or_factory)
    return IntakeRunner(test_settings, session_factory, factory)


def test_run_now_returns_report_and_stores_last(test_settings, session_factory):
    box = FakeMailbox({"1": raw(make_mail(attachments=[("a.pdf", PDF)]))})
    r = runner(test_settings, session_factory, box)
    assert r.last_report is None
    rep = r.run_now()
    assert isinstance(rep, IntakeReport) and rep.status == "klaar" and rep.documents_new == 1
    assert r.last_report is rep and not r.running


def test_not_configured_is_error_report(test_settings, session_factory):
    def factory(settings):
        raise EmailNotConfiguredError()

    rep = runner(test_settings, session_factory, factory).run_now()
    assert rep.status == "fout" and rep.error_code == "EMAIL_NOT_CONFIGURED"
    assert "IMAP_HOST" in rep.error_message


def test_login_error_is_error_report_and_kept_as_last(test_settings, session_factory):
    box = FakeMailbox()
    box.connect_error = EmailLoginFailedError()
    r = runner(test_settings, session_factory, box)
    rep = r.run_now()
    assert rep.status == "fout" and rep.error_code == "EMAIL_LOGIN_FAILED"
    assert r.last_report is rep and box.closed == 1


def test_unexpected_error_becomes_plain_dutch(test_settings, session_factory, caplog):
    box = FakeMailbox()
    box.connect_error = RuntimeError("Traceback secret detail")
    with caplog.at_level(logging.ERROR, logger="app.email_intake"):
        rep = runner(test_settings, session_factory, box).run_now()
    assert rep.status == "fout" and rep.error_code == "EMAIL_IMAP_ERROR"
    assert "secret detail" not in rep.error_message


def test_single_flight(test_settings, session_factory):
    started, release = threading.Event(), threading.Event()

    class SlowBox(FakeMailbox):
        def list_unseen(self):
            started.set()
            release.wait(5)
            return []

    r = runner(test_settings, session_factory, SlowBox())
    results = []
    t = threading.Thread(target=lambda: results.append(r.run_now()))
    t.start()
    assert started.wait(5)
    assert r.running
    second = r.run_now()
    assert isinstance(second, Busy) and second.status == "bezig"
    release.set()
    t.join(5)
    assert results[0].status == "klaar"
    assert isinstance(r.run_now(), IntakeReport)  # lock released


def test_password_never_in_logs(test_settings, session_factory, caplog, monkeypatch):
    import socket
    from app.domain.email_intake import mailbox as mb

    def refuse(*a, **k):
        raise socket.gaierror('no network in tests pw-very-secret')

    monkeypatch.setattr(mb.imaplib, 'IMAP4_SSL', refuse)
    s = Settings(_env_file=None, imap_host="h", imap_user="u", imap_password="pw-very-secret")
    assert "pw-very-secret" not in repr(s) and "pw-very-secret" not in str(s)
    assert s.imap_configured
    with caplog.at_level(logging.DEBUG):
        IntakeRunner(s, session_factory).run_now()  # real ImapMailbox, connection refused
    assert "pw-very-secret" not in caplog.text
