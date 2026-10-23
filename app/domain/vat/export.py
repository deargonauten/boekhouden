"""Export of a BTW-aangifte snapshot: PDF and two CSV files (pure, no database, no clock).

The exports print exactly the numbers in the `ReturnSnapshot`; nothing is recomputed except
the formatting. PDF uses `invariant=1` so the same snapshot always gives the same bytes.
"""

import csv
from io import BytesIO, StringIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.domain.money import format_euro
from app.domain.vat.filing import ReturnSnapshot
from app.domain.vat.periods import VatPeriod
from app.domain.vat.report import TOTAL_LABELS, round_whole_cents

BOM = "﻿"
TOTAL_KEYS = ("5a", "5b", "5c", "5g")
DISCLAIMER = (
    "Dit is een overzicht om over te nemen in Mijn Belastingdienst Zakelijk; het is zelf geen aangifte."
)
UNKNOWN_COUNTRY = "ONBEKEND"
_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def format_csv_cents(cents: int) -> str:
    """Cents as '1234,56' (decimal comma, no thousands separator, '-' for negatives). Integers only."""
    if isinstance(cents, bool) or not isinstance(cents, int):
        raise TypeError("cents must be an int")
    euros, rest = divmod(abs(cents), 100)
    sign = "-" if cents < 0 else ""
    return f"{sign}{euros},{rest:02d}"


def _safe_text(value: str | None) -> str:
    """Neutralise CSV/Excel formula injection in free-text cells."""
    text = value or ""
    return "'" + text if text.startswith(_INJECTION_PREFIXES) else text


def _csv_bytes(rows: list[list[str]]) -> bytes:
    out = StringIO(newline="")
    csv.writer(out, delimiter=";", lineterminator="\r\n").writerows(rows)
    return (BOM + out.getvalue()).encode("utf-8")


def filename_pdf(period: VatPeriod) -> str:
    return f"btw-aangifte-{period.slug}.pdf"


def filename_rubrieken_csv(period: VatPeriod) -> str:
    return f"btw-aangifte-{period.slug}-rubrieken.csv"


def filename_icp_csv(period: VatPeriod) -> str:
    return f"btw-icp-{period.slug}.csv"


def _has_values(line) -> bool:
    return bool(line.grondslag_cents or line.grondslag_whole_cents or line.vat_cents)


def rubrieken_csv(snapshot: ReturnSnapshot) -> bytes:
    """`rubriek;omschrijving;omzet;btw`: rubrieken with values, then 5a, 5b, 5c, 5g."""
    rows = [["rubriek", "omschrijving", "omzet", "btw"]]
    for line in snapshot.lines:
        if _has_values(line):
            rows.append([
                _safe_text(line.rubriek), _safe_text(line.label),
                format_csv_cents(line.grondslag_whole_cents), format_csv_cents(line.vat_cents),
            ])
    for key in TOTAL_KEYS:
        rows.append([key, _safe_text(TOTAL_LABELS[key]), "", format_csv_cents(snapshot.totals.get(key, 0))])
    return _csv_bytes(rows)


def _whole_euros(cents: int) -> str:
    return str(round_whole_cents(cents) // 100)


def icp_csv(snapshot: ReturnSnapshot) -> bytes:
    """`landcode;btw_nummer;goederen;diensten;driehoek` in whole euros, one row per klant.

    Incomplete rows (no klant data yet) are kept with empty cells so the gap stays visible.
    Sales without a linked klant follow as rows with landcode ONBEKEND and an empty btw_nummer,
    so the file never presents an incomplete total as complete.
    """
    rows = [["landcode", "btw_nummer", "goederen", "diensten", "driehoek"]]
    for r in snapshot.icp:
        rows.append([
            _safe_text(r.country), _safe_text(r.btw_number),
            _whole_euros(r.goederen_cents), _whole_euros(r.diensten_cents), _whole_euros(r.driehoek_cents),
        ])
    for u in snapshot.icp_unassigned:
        rows.append([UNKNOWN_COUNTRY, "", _whole_euros(u.goederen_cents), _whole_euros(u.diensten_cents), "0"])
    return _csv_bytes(rows)


# --- PDF ---------------------------------------------------------------------------

MARGIN = 20 * mm
INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#5f6c7b")
RULE = colors.HexColor("#c9d1da")
HEAD_BG = colors.HexColor("#eef1f5")
WARN = colors.HexColor("#b45309")

_BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
_SMALL = ParagraphStyle("small", parent=_BASE, fontSize=8.5, leading=11.5, textColor=MUTED)
_RIGHT = ParagraphStyle("right", parent=_BASE, alignment=TA_RIGHT)
_RIGHT_BOLD = ParagraphStyle("rightbold", parent=_RIGHT, fontName="Helvetica-Bold")
_BOLD = ParagraphStyle("bold", parent=_BASE, fontName="Helvetica-Bold")
_TITLE = ParagraphStyle("title", parent=_BASE, fontName="Helvetica-Bold", fontSize=18, leading=22)
_H2 = ParagraphStyle("h2", parent=_BASE, fontName="Helvetica-Bold", fontSize=12, leading=16, spaceBefore=8)
_HEAD = ParagraphStyle("head", parent=_BASE, fontName="Helvetica-Bold", fontSize=8.5, textColor=MUTED)
_HEAD_RIGHT = ParagraphStyle("headright", parent=_HEAD, alignment=TA_RIGHT)
_CONCEPT = ParagraphStyle("concept", parent=_BASE, fontName="Helvetica-Bold", fontSize=10.5, textColor=WARN)


def _p(text: str, style: ParagraphStyle = _BASE) -> Paragraph:
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def _date(d) -> str:
    return f"{d:%d-%m-%Y}"


def _table(data, widths) -> Table:
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def aangifte_pdf(snapshot: ReturnSnapshot) -> bytes:
    """A4 overview of the aangifte: rubrieken, totals and ICP table. Deterministic bytes."""
    width = A4[0] - 2 * MARGIN
    story: list = []
    title = f"BTW-aangifte {snapshot.period.label}"
    story.append(_p(title + (" (CONCEPT)" if snapshot.is_concept else ""), _TITLE))
    story.append(Spacer(1, 3 * mm))
    if snapshot.is_concept:
        story.append(_p("CONCEPT: deze aangifte is nog niet ingediend en kan nog veranderen.", _CONCEPT))
        story.append(Spacer(1, 2 * mm))
    meta = [
        ("Bedrijf", snapshot.company_name),
        ("BTW-id", snapshot.btw_id or "-"),
        ("Periode", snapshot.period.label),
        ("Status", "Concept" if snapshot.is_concept else "Ingediend"),
    ]
    if snapshot.filed_on:
        meta.append(("Ingediend op", _date(snapshot.filed_on)))
    if snapshot.reference:
        meta.append(("Referentie", snapshot.reference))
    mt = Table([[_p(k, _SMALL), _p(v, _BOLD)] for k, v in meta], colWidths=[35 * mm, width - 35 * mm])
    mt.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 1),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    story.append(mt)

    story.append(_p("Rubrieken", _H2))
    rows = [[_p("Rubriek", _HEAD), _p("Omschrijving", _HEAD), _p("Omzet (hele euro's)", _HEAD_RIGHT),
             _p("BTW", _HEAD_RIGHT)]]
    shown = [l for l in snapshot.lines if _has_values(l)]
    for l in shown:
        rows.append([_p(l.rubriek, _BOLD), _p(l.label), _p(format_euro(l.grondslag_whole_cents), _RIGHT),
                     _p(format_euro(l.vat_cents), _RIGHT)])
    if not shown:
        rows.append([_p(""), _p("Geen btw in deze periode", _SMALL), _p(""), _p("")])
    for key in TOTAL_KEYS:
        rows.append([_p(key, _BOLD), _p(TOTAL_LABELS[key], _BOLD if key == "5g" else _BASE), _p(""),
                     _p(format_euro(snapshot.totals.get(key, 0)), _RIGHT_BOLD if key == "5g" else _RIGHT)])
    story.append(_table(rows, [18 * mm, width - 18 * mm - 70 * mm, 40 * mm, 30 * mm]))

    story.append(_p("ICP-opgaaf (verkopen aan bedrijven in de EU)", _H2))
    if snapshot.icp:
        irows = [[_p("Land", _HEAD), _p("BTW-nummer", _HEAD), _p("Klant", _HEAD),
                  _p("Goederen", _HEAD_RIGHT), _p("Diensten", _HEAD_RIGHT)]]
        for r in snapshot.icp:
            name = r.name or ""
            if r.issue:
                name = (name + " - " if name else "") + "Onvolledig: " + r.issue
            irows.append([_p(r.country or "-"), _p(r.btw_number or "-"), _p(name),
                          _p(format_euro(round_whole_cents(r.goederen_cents)), _RIGHT),
                          _p(format_euro(round_whole_cents(r.diensten_cents)), _RIGHT)])
        story.append(_table(irows, [14 * mm, 38 * mm, width - 14 * mm - 38 * mm - 56 * mm, 28 * mm, 28 * mm]))
    elif not snapshot.icp_unassigned:
        story.append(_p("Geen EU-verkopen in deze periode.", _SMALL))
    if snapshot.icp_unassigned:
        story.append(_p("Nog geen klant gekoppeld", _H2))
        story.append(_p(
            "Bij deze verkopen aan bedrijven in de EU ontbreken het land en het btw-nummer van de klant. "
            "De ICP-opgaaf is daarom nog niet compleet. Koppel eerst bij elke boeking een klant "
            "(met land en btw-nummer) voordat je de ICP-opgaaf afrondt.", _BASE))
        story.append(Spacer(1, 2 * mm))
        urows = [[_p("Boeking", _HEAD), _p("Omschrijving", _HEAD), _p("Goederen", _HEAD_RIGHT),
                  _p("Diensten", _HEAD_RIGHT)]]
        for u in snapshot.icp_unassigned:
            urows.append([_p(u.entry_number), _p(u.description),
                          _p(format_euro(round_whole_cents(u.goederen_cents)), _RIGHT),
                          _p(format_euro(round_whole_cents(u.diensten_cents)), _RIGHT)])
        story.append(_table(urows, [26 * mm, width - 26 * mm - 56 * mm, 28 * mm, 28 * mm]))

    story.append(Spacer(1, 6 * mm))
    story.append(_p(DISCLAIMER, _SMALL))

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=18 * mm, bottomMargin=18 * mm,
        title=title, author=snapshot.company_name or "", invariant=1,
    )
    doc.build(story)
    return buf.getvalue()
