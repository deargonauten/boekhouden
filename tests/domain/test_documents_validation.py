import pytest

from app.domain.documents.validation import (
    MAX_DOCUMENT_BYTES,
    check_size,
    format_size,
    sanitize_filename,
    sniff_type,
    validate_content,
)
from app.domain.errors import (
    DocumentError,
    EmptyFileError,
    FileTooLargeError,
    LedgerError,
    UnsupportedFileTypeError,
)

PDF = b"%PDF-1.7\n%...\n"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 20
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 20


def _ftyp(brand: bytes) -> bytes:
    return b"\x00\x00\x00\x18ftyp" + brand + b"\x00" * 16


def test_max_is_20_mb():
    assert MAX_DOCUMENT_BYTES == 20 * 1024 * 1024


@pytest.mark.parametrize(
    "data,ctype,ext",
    [
        (PDF, "application/pdf", "pdf"),
        (b"junk" * 100 + PDF, "application/pdf", "pdf"),
        (JPEG, "image/jpeg", "jpg"),
        (PNG, "image/png", "png"),
        (WEBP, "image/webp", "webp"),
    ],
)
def test_sniff_accepts(data, ctype, ext):
    detected = sniff_type(data)
    assert (detected.content_type, detected.ext) == (ctype, ext)


def test_pdf_header_must_be_within_first_1024_bytes():
    assert sniff_type(b"x" * 1019 + b"%PDF-").ext == "pdf"
    with pytest.raises(UnsupportedFileTypeError):
        sniff_type(b"x" * 1020 + b"%PDF-")


def test_content_wins_over_name():
    # sniff_type only sees bytes: a jpeg is a jpeg whatever it was called
    assert sniff_type(JPEG).content_type == "image/jpeg"


@pytest.mark.parametrize(
    "data", [b"hello world, just text", b"RIFF\x00\x00\x00\x00WAVEfmt ", b"\x89PNG", b"\xff\xd8"]
)
def test_sniff_rejects_other(data):
    with pytest.raises(UnsupportedFileTypeError) as exc:
        sniff_type(data)
    assert exc.value.code == "UNSUPPORTED_FILE_TYPE"
    assert exc.value.message == (
        "Dit bestandstype kan niet worden verwerkt. Kies een PDF, JPEG, PNG of WebP-bestand."
    )
    assert isinstance(exc.value, DocumentError) and isinstance(exc.value, LedgerError)


@pytest.mark.parametrize("brand", [b"heic", b"heix", b"heif", b"mif1", b"hevc"])
def test_heic_has_own_message(brand):
    with pytest.raises(UnsupportedFileTypeError) as exc:
        sniff_type(_ftyp(brand))
    assert exc.value.message == (
        "Dit lijkt een HEIC-foto (iPhone). Zet de foto om naar JPEG, of stel je camera in op "
        "'Meest compatibel', en probeer het opnieuw."
    )


def test_other_ftyp_brand_is_generic_unsupported():
    with pytest.raises(UnsupportedFileTypeError) as exc:
        sniff_type(_ftyp(b"mp42"))
    assert "HEIC" not in exc.value.message


def test_empty_file():
    with pytest.raises(EmptyFileError) as exc:
        check_size(0)
    assert exc.value.code == "EMPTY_FILE"
    assert exc.value.message == "Dit bestand is leeg. Kies een ander bestand."


def test_size_boundary():
    check_size(MAX_DOCUMENT_BYTES)
    with pytest.raises(FileTooLargeError) as exc:
        check_size(MAX_DOCUMENT_BYTES + 1)
    assert exc.value.code == "FILE_TOO_LARGE"


def test_too_large_message_uses_comma_mb():
    with pytest.raises(FileTooLargeError) as exc:
        check_size(254 * 1024 * 1024 // 10 + 1)
    assert exc.value.message == (
        "Dit bestand is te groot (25,4 MB). De grens is 20 MB. "
        "Maak de PDF kleiner of fotografeer met een lagere resolutie."
    )


def test_validate_content_order_empty_then_size_then_type():
    with pytest.raises(EmptyFileError):
        validate_content(b"")
    with pytest.raises(FileTooLargeError):
        validate_content(b"x" * (MAX_DOCUMENT_BYTES + 1))  # also wrong type: size wins
    with pytest.raises(UnsupportedFileTypeError):
        validate_content(b"plain text")
    assert validate_content(PDF).ext == "pdf"


def test_validate_content_exactly_20_mb_accepted():
    data = PDF + b"0" * (MAX_DOCUMENT_BYTES - len(PDF))
    assert len(data) == MAX_DOCUMENT_BYTES
    assert validate_content(data).ext == "pdf"


@pytest.mark.parametrize(
    "size,expected",
    [
        (1, "1 bytes"),
        (1023, "1023 bytes"),
        (2048, "2 KB"),
        (1024 * 1024, "1,0 MB"),
        (int(1.25 * 1024 * 1024), "1,2 MB"),
        (20 * 1024 * 1024, "20,0 MB"),
    ],
)
def test_format_size(size, expected):
    assert format_size(size) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("factuur.pdf", "factuur.pdf"),
        ("../../x.pdf", "x.pdf"),
        ("..\\..\\x.pdf", "x.pdf"),
        ("/etc/passwd", "passwd"),
        ("C:\\Users\\jan\\bon.jpg", "bon.jpg"),
        ("a/b/c.png", "c.png"),
        ("fac\x00tuur\x07.pdf", "factuur.pdf"),
        ("line\nbreak\r.pdf", "linebreak.pdf"),
        ("  spaced name.pdf  ", "spaced name.pdf"),
        ("Café – bon €12.pdf", "Café – bon €12.pdf"),
        ("", "document.pdf"),
        ("   ", "document.pdf"),
        ("..", "document.pdf"),
        (".", "document.pdf"),
        ("folder/", "document.pdf"),
        ("\x00\x01", "document.pdf"),
    ],
)
def test_sanitize_filename(raw, expected):
    assert sanitize_filename(raw, "pdf") == expected


def test_sanitize_none():
    assert sanitize_filename(None, "jpg") == "document.jpg"


def test_sanitize_long_name_capped_at_255_keeps_extension():
    out = sanitize_filename("a" * 300 + ".pdf", "pdf")
    assert len(out) == 255
    assert out.endswith(".pdf")


def test_sanitize_long_name_without_extension():
    assert len(sanitize_filename("b" * 400, "pdf")) == 255
