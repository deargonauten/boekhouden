import hashlib
from email.message import EmailMessage as Mail

from app.domain.email_intake import extract_attachments, read_mail_info
from app.domain.email_intake.parsing import MAX_CANDIDATES
from tests.email_intake.conftest import BIG_JPEG, HEIC, JPEG, PDF, PDF2, PNG, make_mail, raw


def names(result):
    return [c.filename for c in result.candidates]


def test_plain_pdf_attachment():
    r = extract_attachments(raw(make_mail(attachments=[("f.pdf", PDF)])))
    assert names(r) == ["f.pdf"]
    assert r.candidates[0].content == PDF and r.candidates[0].origin == "bijlage"
    assert r.skipped == []


def test_jpeg_and_png():
    r = extract_attachments(raw(make_mail(attachments=[("a.jpg", BIG_JPEG, "image/jpeg"), ("b.png", PNG + b"x" * 40000, "image/png")])))
    assert names(r) == ["a.jpg", "b.png"]


def test_sniffs_content_not_declared_type_or_extension():
    r = extract_attachments(raw(make_mail(attachments=[("factuur.bin", PDF, "application/octet-stream")])))
    assert names(r) == ["factuur.bin"]


def test_missing_filename_gets_default():
    msg = make_mail()
    msg.add_attachment(PDF, maintype="application", subtype="pdf")
    r = extract_attachments(raw(msg))
    assert names(r) == ["bijlage.pdf"]


def test_rfc2231_filename_decoded():
    msg = make_mail()
    msg.add_attachment(PDF, maintype="application", subtype="pdf", filename="factuur é.pdf")
    r = extract_attachments(raw(msg))
    assert names(r) == ["factuur é.pdf"]


def test_forwarded_message_rfc822():
    inner = make_mail(subject="Orig", message_id="<in@x>", attachments=[("inner.pdf", PDF)])
    outer = make_mail(subject="Fwd")
    outer.add_attachment(inner)  # message/rfc822
    r = extract_attachments(raw(outer))
    assert names(r) == ["inner.pdf"]
    assert r.candidates[0].origin == "doorgestuurd"


def test_eml_attachment_as_octet_stream():
    inner = make_mail(subject="Orig", attachments=[("inner.pdf", PDF)])
    outer = make_mail(subject="Fwd", attachments=[("orig.eml", raw(inner), "application/octet-stream")])
    r = extract_attachments(raw(outer))
    assert names(r) == ["inner.pdf"]
    assert r.candidates[0].origin == "doorgestuurd"


def test_nested_twice():
    innermost = make_mail(subject="A", attachments=[("deep.pdf", PDF)])
    middle = make_mail(subject="B")
    middle.add_attachment(innermost)
    outer = make_mail(subject="C")
    outer.add_attachment(middle)
    assert names(extract_attachments(raw(outer))) == ["deep.pdf"]


def test_nesting_depth_limit():
    msg = make_mail(attachments=[("deep.pdf", PDF)])
    for i in range(7):
        wrapper = make_mail(subject=f"w{i}")
        wrapper.add_attachment(msg)
        msg = wrapper
    r = extract_attachments(raw(msg))
    assert r.candidates == []
    assert any("diep" in s.reason for s in r.skipped)


def test_same_pdf_twice_in_forward_appears_once():
    inner = make_mail(attachments=[("a.pdf", PDF)])
    outer = make_mail(attachments=[("b.pdf", PDF)])
    outer.add_attachment(inner)
    r = extract_attachments(raw(outer))
    assert names(r) == ["b.pdf"]


def test_candidate_cap():
    atts = [(f"{i}.pdf", PDF + str(i).encode()) for i in range(MAX_CANDIDATES + 3)]
    r = extract_attachments(raw(make_mail(attachments=atts)))
    assert len(r.candidates) == MAX_CANDIDATES
    assert len(r.skipped) == 3


def test_small_inline_logo_ignored_large_inline_kept_attachment_kept():
    msg = Mail()
    msg["Subject"] = "x"
    msg.set_content("hi")
    msg.add_attachment(JPEG, maintype="image", subtype="jpeg", disposition="inline", cid="<logo>")
    msg.add_attachment(BIG_JPEG + b"1", maintype="image", subtype="jpeg", disposition="inline", cid="<foto>", filename="foto.jpg")
    msg.add_attachment(JPEG + b"2", maintype="image", subtype="jpeg", filename="bon.jpg")
    r = extract_attachments(raw(msg))
    assert sorted(names(r)) == ["bon.jpg", "foto.jpg"]
    assert r.skipped == []


def test_inline_gif_pixel_ignored_silently():
    msg = Mail()
    msg["Subject"] = "x"
    msg.set_content("hi")
    msg.add_attachment(b"GIF89a" + b"\x00" * 10, maintype="image", subtype="gif", disposition="inline", cid="<p>")
    r = extract_attachments(raw(msg))
    assert r.candidates == [] and r.skipped == []


def test_heic_and_docx_skipped_with_reason():
    r = extract_attachments(
        raw(make_mail(attachments=[("a.heic", HEIC, "image/heic"), ("b.docx", b"PK\x03\x04zip", "application/zip")]))
    )
    assert r.candidates == []
    reasons = {s.filename: s.reason for s in r.skipped}
    assert reasons["a.heic"] == "Foto's in HEIC-formaat worden niet ondersteund; stuur JPEG of PNG"
    assert reasons["b.docx"] == "Bestandstype wordt niet ondersteund (alleen PDF en foto's)"


def test_text_parts_and_signatures_ignored_silently():
    msg = make_mail()
    msg.add_alternative("<p>html</p>", subtype="html")
    msg.add_attachment(b"-----BEGIN PGP", maintype="application", subtype="pgp-signature", filename="sig.asc")
    r = extract_attachments(raw(msg))
    assert r.candidates == [] and r.skipped == []


def test_no_attachments():
    r = extract_attachments(raw(make_mail()))
    assert r.candidates == [] and r.skipped == []


def test_corrupt_nested_eml_skipped_not_raised():
    outer = make_mail(attachments=[("kapot.eml", b"\x00\x01\x02 not a mail", "application/octet-stream")])
    r = extract_attachments(raw(outer))
    assert r.candidates == []
    assert r.skipped and r.skipped[0].filename == "kapot.eml"


def test_garbage_input_never_raises():
    for data in (b"", b"\xff\xfe\x00garbage", b"Content-Type: multipart/mixed\n\n--x\n"):
        extract_attachments(data)


def test_mail_info_basic():
    info = read_mail_info(raw(make_mail(subject="Hallo", message_id="<ABC@Example.com>")))
    assert info.message_key == "abc@example.com"
    assert info.subject == "Hallo"
    assert "lev@example.com" in info.from_addr
    assert info.received_at.tzinfo is None
    assert (info.received_at.hour, info.received_at.day) == (8, 5)  # +0200 -> UTC


def test_mail_info_without_message_id_uses_hash():
    data = raw(make_mail(message_id=None))
    info = read_mail_info(data)
    assert info.message_key == "sha256:" + hashlib.sha256(data).hexdigest()


def test_mail_info_truncates_and_decodes():
    msg = make_mail(subject="é" * 300)
    info = read_mail_info(raw(msg))
    assert len(info.subject) == 200 and info.subject.startswith("é")


def test_mail_info_bad_date_falls_back_to_now():
    msg = make_mail()
    del msg["Date"]
    msg["Date"] = "geen datum"
    assert read_mail_info(raw(msg)).received_at.year >= 2026
