"""Manual, opt-in smoke tests. Skipped by default (and not for CI).

Run with a logged-in CLI:  pytest -m live tests/extraction/extractors/test_live.py
Early-warning check for `claude` CLI flag drift (spec D12). Uses the real
`claude` binary and counts against your plan (a few cents with the haiku alias).
"""

import pytest

from app.config import Settings
from app.domain.extraction.extractors.claude_cli import ClaudeCliExtractor
from app.domain.extraction.extractors.factory import cli_status
from app.domain.extraction.types import AccountHint, ExtractionRequest

pytestmark = pytest.mark.live


def _pdf() -> bytes:
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 300] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    s = (
        b"BT /F1 14 Tf 20 250 Td (Factuur 2026-001 van Bakkerij Jansen) Tj 0 -20 Td "
        b"(Datum 2026-03-04) Tj 0 -20 Td (Brood 10,00 excl, BTW 9% 0,90, totaal 10,90) Tj ET"
    )
    objs.append(b"<< /Length %d >>\nstream\n" % len(s) + s + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets:
        out += b"%010d 00000 n \n" % o
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


def test_real_cli_reads_sample_pdf():
    if cli_status(Settings(_env_file=None)) != "ready":
        pytest.skip("claude CLI not installed or not logged in")
    request = ExtractionRequest(
        content=_pdf(),
        content_type="application/pdf",
        filename="sample.pdf",
        accounts=(AccountHint("4100", "Kantoorkosten"),),
        vat_codes=("NL_21", "NL_9", "NL_0"),
    )
    invoice = ClaudeCliExtractor(model="haiku", timeout_seconds=180).extract(request)
    assert invoice.supplier.name and "Jansen" in invoice.supplier.name
    assert invoice.invoice_number == "2026-001"
    assert invoice.total_incl_cents == 1090
