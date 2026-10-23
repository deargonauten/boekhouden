import pytest
from sqlalchemy import func, select

from app.domain.documents import service as docs
from app.domain.documents.storage import DocumentStorage
from app.domain.email_intake import EmailConnectFailedError, recent_messages, run_intake
from app.models import Document, EmailMessage
from tests.email_intake.conftest import HEIC, JPEG, PDF, PDF2, FakeMailbox, make_mail, raw


def mail(n, *atts, key=None, subject=None):
    return raw(make_mail(subject=subject or f"Factuur {n}", message_id=key or f"<m{n}@x>", attachments=list(atts)))


def run(session_factory, storage, box, max_messages=50):
    return run_intake(session_factory, storage, box, max_messages=max_messages)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_stores_documents_and_moves(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF)), "2": mail(2, ("b.pdf", PDF2))})
    rep = run(session_factory, storage, box)
    assert (rep.mails_seen, rep.mails_processed, rep.documents_new) == (2, 2, 2)
    assert box.processed == ["1", "2"] and box.closed == 1
    session.expire_all()
    docs_ = session.scalars(select(Document).order_by(Document.id)).all()
    assert [d.source for d in docs_] == ["email", "email"]
    assert docs_[0].status == "nieuw"
    assert docs_[0].source_ref == "Leverancier <lev@example.com> - Factuur 1"
    assert docs_[0].received_at.day == 5
    assert all(m.moved for m in session.scalars(select(EmailMessage)))


def test_second_run_is_idempotent(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF))})
    run(session_factory, storage, box)
    again = FakeMailbox({"9": mail(1, ("a.pdf", PDF))})  # same Message-ID re-appears
    rep = run(session_factory, storage, again)
    assert rep.documents_new == 0 and again.processed == ["9"]
    assert count(session, Document) == 1 and count(session, EmailMessage) == 1
    rep2 = run(session_factory, storage, box)
    assert rep2.mails_seen == 0 and rep2.documents_new == 0


def test_same_pdf_in_two_mails_one_document(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF)), "2": mail(2, ("again.pdf", PDF))})
    rep = run(session_factory, storage, box)
    assert (rep.documents_new, rep.documents_duplicate) == (1, 1)
    assert count(session, Document) == 1
    outcomes = [m.outcome for m in session.scalars(select(EmailMessage).order_by(EmailMessage.id))]
    assert outcomes == ["opgeslagen", "alleen_dubbel"]


def test_duplicate_of_manual_upload_or_booked_keeps_status(session, session_factory, storage):
    docs.add_document(session, storage, PDF, "hand.pdf")
    session.commit()
    document = session.scalar(select(Document))
    session.execute(Document.__table__.update().values(status="herkend"))
    session.commit()
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF))})
    rep = run(session_factory, storage, box)
    assert rep.documents_new == 0 and rep.documents_duplicate == 1
    session.expire_all()
    assert session.get(Document, document.id).status == "herkend"
    assert session.get(Document, document.id).source == "upload"


def test_mail_without_attachment_recorded_and_moved(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1)})
    rep = run(session_factory, storage, box)
    assert rep.mails_without_attachments == 1 and box.processed == ["1"]
    assert session.scalar(select(EmailMessage.outcome)) == "geen_bijlage"
    assert "zonder PDF of foto" in rep.summary()


def test_only_invalid_attachments_handled_like_no_attachment(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.heic", HEIC, "image/heic"))})
    rep = run(session_factory, storage, box)
    assert rep.mails_without_attachments == 1 and rep.attachments_skipped == 1
    assert any("HEIC" in p for p in rep.problems)
    assert box.processed == ["1"]


def test_invalid_attachment_does_not_fail_mail_with_valid_one(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF), ("b.docx", b"PK\x03\x04", "application/zip"))})
    rep = run(session_factory, storage, box)
    assert (rep.documents_new, rep.attachments_skipped, rep.mails_failed) == (1, 1, 0)
    assert len(rep.problems) == 1 and "b.docx" in rep.problems[0]


def test_store_failure_isolated_then_retried(session, session_factory, storage, monkeypatch):
    from app.domain.email_intake import service as svc
    from app.domain.errors import DocumentStorageFailedError

    real = svc.add_document

    def flaky(sess, stor, content, filename, **kw):
        if filename == "bad.pdf":
            raise DocumentStorageFailedError("kapot")
        return real(sess, stor, content, filename, **kw)

    monkeypatch.setattr(svc, "add_document", flaky)
    box = FakeMailbox(
        {
            "1": mail(1, ("a.pdf", PDF)),
            "2": mail(2, ("bad.pdf", PDF2)),
            "3": mail(3, ("c.pdf", PDF + b"3")),
        }
    )
    rep = run(session_factory, storage, box)
    assert rep.mails_failed == 1 and rep.documents_new == 2
    assert box.processed == ["1", "3"]
    assert any("Factuur 2" in p and "opnieuw" in p for p in rep.problems)
    assert count(session, EmailMessage) == 2

    monkeypatch.setattr(svc, "add_document", real)
    rep2 = run(session_factory, storage, box)
    assert rep2.documents_new == 1 and box.processed == ["1", "3", "2"]


def test_fetch_failure_isolated(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF)), "2": mail(2, ("b.pdf", PDF2))})
    box.fail_fetch.add("1")
    rep = run(session_factory, storage, box)
    assert rep.mails_failed == 1 and rep.documents_new == 1 and box.processed == ["2"]


def test_move_failure_after_commit_no_duplicate_on_retry(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF))})
    box.fail_mark.add("1")
    rep = run(session_factory, storage, box)
    assert rep.documents_new == 1 and rep.mails_failed == 0
    assert any("kon niet naar de map Verwerkt worden verplaatst" in p for p in rep.problems)
    assert session.scalar(select(EmailMessage.moved)) is False

    box.fail_mark.clear()
    rep2 = run(session_factory, storage, box)
    assert rep2.documents_new == 0 and rep2.documents_duplicate == 0
    assert box.processed == ["1"] and count(session, Document) == 1
    session.expire_all()
    assert session.scalar(select(EmailMessage.moved)) is True


def test_max_messages_cap(session, session_factory, storage):
    box = FakeMailbox({str(i): mail(i, ("a.pdf", PDF + str(i).encode())) for i in range(1, 6)})
    rep = run(session_factory, storage, box, max_messages=2)
    assert rep.mails_seen == 2 and box.processed == ["1", "2"]
    rep2 = run(session_factory, storage, box, max_messages=2)
    assert box.processed == ["1", "2", "3", "4"] and rep2.documents_new == 2


def test_oversized_mail_not_fetched(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF))})
    box.sizes["1"] = 51 * 1024 * 1024
    rep = run(session_factory, storage, box)
    assert box.fetched == [] and box.processed == []
    assert rep.mails_failed == 1 and "50 MB" in rep.problems[0]


def test_connection_error_aborts_and_closes(session_factory, storage):
    box = FakeMailbox()
    box.connect_error = EmailConnectFailedError("imap.x")
    with pytest.raises(EmailConnectFailedError):
        run(session_factory, storage, box)
    assert box.closed == 1


def test_documents_never_removed(session_factory, storage, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("remove must not be called")

    monkeypatch.setattr(DocumentStorage, "remove", boom)
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF)), "2": mail(2, ("a.pdf", PDF)), "3": mail(3)})
    box.fail_mark.add("2")
    run(session_factory, storage, box)


def test_message_without_message_id_deduped_by_hash(session, session_factory, storage):
    data = raw(make_mail(message_id=None, attachments=[("a.pdf", PDF)]))
    run(session_factory, storage, FakeMailbox({"1": data}))
    rep = run(session_factory, storage, FakeMailbox({"5": data}))
    assert rep.documents_new == 0 and count(session, EmailMessage) == 1


def test_deleted_document_does_not_return_from_same_mail(session, session_factory, storage):
    box = FakeMailbox({"1": mail(1, ("a.pdf", PDF))})
    run(session_factory, storage, box)
    doc = session.scalar(select(Document))
    docs.delete_document(session, storage, doc.id)
    session.commit()
    rep = run(session_factory, storage, FakeMailbox({"7": mail(1, ("a.pdf", PDF))}))
    assert rep.documents_new == 0 and count(session, Document) == 0


def test_recent_messages_newest_first_limited(session, session_factory, storage):
    box = FakeMailbox({str(i): mail(i, ("a.pdf", PDF + str(i).encode())) for i in range(1, 5)})
    run(session_factory, storage, box)
    recent = recent_messages(session, 3)
    assert [m.subject for m in recent] == ["Factuur 4", "Factuur 3", "Factuur 2"]


def test_summary_texts(session_factory, storage):
    rep = run(session_factory, storage, FakeMailbox())
    assert rep.summary() == "Geen nieuwe mail met facturen gevonden."
    box = FakeMailbox(
        {"1": mail(1, ("a.pdf", PDF), ("b.pdf", PDF2), ("c.pdf", PDF + b"c")), "2": mail(2, ("d.pdf", PDF))}
    )
    rep = run(session_factory, storage, box)
    assert rep.summary() == "Klaar: 3 nieuwe documenten uit je mailbox gehaald, 1 stond er al."
