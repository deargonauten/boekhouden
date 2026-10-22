"""Export of a BTW-aangifte snapshot: CSV formats, PDF validity/determinism, filenames."""

from datetime import date
from io import BytesIO

import pytest
from pypdf import PdfReader

from app.domain.vat import VatPeriod
from app.domain.vat.export import (
    DISCLAIMER,
    aangifte_pdf,
    filename_icp_csv,
    filename_pdf,
    filename_rubrieken_csv,
    format_csv_cents,
    icp_csv,
    rubrieken_csv,
)
from app.domain.vat.filing import ReturnSnapshot
from app.domain.vat.icp import IcpRow
from app.domain.vat.report import RubriekLine

Q3 = VatPeriod(2026, "quarter", 3)


def line(rubriek, grondslag, vat, side="sales", label=None):
    whole = grondslag // 100 * 100 if grondslag >= 0 else -(abs(grondslag) // 100 * 100)
    return RubriekLine(rubriek, side, label or f"Omschrijving {rubriek}", grondslag, whole, vat)


def snapshot(lines=None, icp=None, *, concept=True, totals=None, period=Q3, name="Jansen Advies"):
    return ReturnSnapshot(
        period=period, status="concept" if concept else "ingediend", company_name=name,
        btw_id="NL123456789B01", lines=lines or [], totals=totals or {"5a": 0, "5b": 0, "5c": 0, "5g": 0},
        icp=icp or [], icp_unassigned=[], warnings=[], filed_on=None if concept else date(2026, 10, 5),
        reference=None if concept else "REF-1", is_concept=concept,
    )


def rows_of(data: bytes) -> list[list[str]]:
    assert data.startswith(b"\xef\xbb\xbf")
    text = data.decode("utf-8-sig")
    return [r.split(";") for r in text.split("\r\n") if r]


@pytest.mark.parametrize(
    ("cents", "expected"),
    [(0, "0,00"), (5, "0,05"), (123456, "1234,56"), (100000000, "1000000,00"), (-1, "-0,01"), (-123456, "-1234,56")],
)
def test_format_csv_cents(cents, expected):
    assert format_csv_cents(cents) == expected


def test_format_csv_cents_rejects_floats_and_bools():
    for bad in (1.5, True, "1"):
        with pytest.raises(TypeError):
            format_csv_cents(bad)


def test_rubrieken_csv_shape_and_amounts():
    s = snapshot(
        [line("1a", 123499, 25935), line("1b", 0, 0), line("4b", 5000, 1050, "purchase")],
        totals={"5a": 25935, "5b": 1050, "5c": 24885, "5g": 24885},
    )
    data = rubrieken_csv(s)
    rows = rows_of(data)
    assert rows[0] == ["rubriek", "omschrijving", "omzet", "btw"]
    assert rows[1] == ["1a", "Omschrijving 1a", "1234,00", "259,35"]  # whole euros, rounded down
    assert rows[2][0] == "4b" and rows[2][2:] == ["50,00", "10,50"]
    assert [r[0] for r in rows[3:]] == ["5a", "5b", "5c", "5g"]
    assert rows[-1][2:] == ["", "248,85"]
    assert b"1b" not in data  # rubrieken without values are left out
    assert data.endswith(b"\r\n")


def test_rubrieken_csv_empty_still_has_totals():
    rows = rows_of(rubrieken_csv(snapshot()))
    assert [r[0] for r in rows] == ["rubriek", "5a", "5b", "5c", "5g"]
    assert all(r[3] == "0,00" for r in rows[1:])


def test_rubrieken_csv_negative_amounts():
    s = snapshot([line("1a", -123499, -25935)], totals={"5a": -25935, "5b": 0, "5c": -25935, "5g": -25935})
    rows = rows_of(rubrieken_csv(s))
    assert rows[1][2:] == ["-1234,00", "-259,35"]
    assert rows[-1][3] == "-259,35"


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_csv_injection_prefix_in_text_cells(prefix):
    s = snapshot([line("1a", 100, 21, label=f"{prefix}HYPERLINK(1)")])
    assert rows_of(rubrieken_csv(s))[1][1] == f"'{prefix}HYPERLINK(1)"
    icp = snapshot(icp=[IcpRow(country="DE", btw_number=f"{prefix}123", goederen_cents=100, diensten_cents=0)])
    assert rows_of(icp_csv(icp))[1][1] == f"'{prefix}123"


def test_csv_leaves_normal_text_alone():
    assert rows_of(rubrieken_csv(snapshot([line("1a", 100, 21, label="Omzet 21%")])))[1][1] == "Omzet 21%"


def test_icp_csv_whole_euros_and_columns():
    s = snapshot(icp=[
        IcpRow(country="DE", btw_number="123456789", goederen_cents=150099, diensten_cents=99, name="Klant"),
        IcpRow(country="FR", btw_number="", goederen_cents=0, diensten_cents=250000, issue="Vul btw-nummer in"),
    ])
    rows = rows_of(icp_csv(s))
    assert rows[0] == ["landcode", "btw_nummer", "goederen", "diensten", "driehoek"]
    assert rows[1] == ["DE", "123456789", "1500", "0", "0"]
    assert rows[2] == ["FR", "", "0", "2500", "0"]  # incomplete rows stay visible


def test_icp_csv_empty_is_header_only():
    assert len(rows_of(icp_csv(snapshot()))) == 1


def test_icp_csv_negative_whole_euros():
    s = snapshot(icp=[IcpRow(country="DE", btw_number="1", goederen_cents=-150099, diensten_cents=0)])
    assert rows_of(icp_csv(s))[1][2] == "-1500"


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(BytesIO(data)).pages)


def test_pdf_is_valid_with_period_btw_id_and_disclaimer():
    s = snapshot(
        [line("1a", 123499, 25935)], totals={"5a": 25935, "5b": 0, "5c": 25935, "5g": 25935},
        icp=[IcpRow(country="DE", btw_number="123456789", goederen_cents=100000, diensten_cents=0, name="Klant")],
        concept=False,
    )
    data = aangifte_pdf(s)
    assert data.startswith(b"%PDF")
    text = pdf_text(data)
    assert "3e kwartaal 2026" in text
    assert "NL123456789B01" in text
    assert "Jansen Advies" in text
    assert "Ingediend" in text and "REF-1" in text
    assert "259,35" in text
    assert "123456789" in text
    assert " ".join(DISCLAIMER.split()) in " ".join(text.split())
    assert "CONCEPT" not in text


def test_pdf_concept_is_labelled():
    assert "CONCEPT" in pdf_text(aangifte_pdf(snapshot()))


def test_pdf_marks_incomplete_icp_rows_and_empty_states():
    s = snapshot(icp=[IcpRow(country="DE", btw_number="", goederen_cents=1000, diensten_cents=0,
                             issue="Vul het btw-nummer van de klant in")])
    text = " ".join(pdf_text(aangifte_pdf(s)).split())
    assert "Onvolledig" in text and "Vul het btw-nummer" in text
    assert "Geen btw in deze periode" in text
    assert "Geen EU-verkopen" in " ".join(pdf_text(aangifte_pdf(snapshot())).split())


def test_pdf_escapes_markup_in_names():
    data = aangifte_pdf(snapshot(name="A <b>&</b> B"))
    assert "A <b>&</b> B" in pdf_text(data)


def test_pdf_is_deterministic():
    s = snapshot([line("1a", 123499, 25935)], concept=False)
    assert aangifte_pdf(s) == aangifte_pdf(s)


def test_filenames_use_slug():
    assert filename_pdf(Q3) == "btw-aangifte-2026-Q3.pdf"
    assert filename_rubrieken_csv(Q3) == "btw-aangifte-2026-Q3-rubrieken.csv"
    assert filename_icp_csv(Q3) == "btw-icp-2026-Q3.csv"
    assert filename_pdf(VatPeriod(2026, "month", 7)) == "btw-aangifte-2026-M07.pdf"
