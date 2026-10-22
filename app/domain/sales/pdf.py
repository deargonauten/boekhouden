"""PDF rendering of verkoopfacturen, creditnota's and betalingsherinneringen (ReportLab platypus).

Pure functions on frozen snapshots: no database, no Session, no clock. A4, built-in Helvetica
(the euro sign is part of WinAnsi), `invariant=1` so the same data always gives the same bytes.
The PDF prints exactly the numbers stored in the snapshot (it never recomputes amounts).
"""

from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.domain.money import format_euro
from app.domain.sales.amounts import format_quantity
from app.domain.sales.types import CREDIT_NOTE, InvoiceDocument, ReminderDocument

PAGE_W, PAGE_H = A4
MARGIN_X = 20 * mm
MARGIN_TOP = 18 * mm
MARGIN_BOTTOM = 26 * mm  # room for the footer with the own company data
CONTENT_W = PAGE_W - 2 * MARGIN_X

INK = colors.HexColor("#1f2933")
MUTED = colors.HexColor("#5f6c7b")
RULE = colors.HexColor("#c9d1da")
HEAD_BG = colors.HexColor("#eef1f5")

_BASE = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK)
S_TEXT = _BASE
S_SMALL = ParagraphStyle("small", parent=_BASE, fontSize=8.5, leading=11.5, textColor=MUTED)
S_RIGHT = ParagraphStyle("right", parent=_BASE, alignment=TA_RIGHT)
S_RIGHT_BOLD = ParagraphStyle("rightbold", parent=S_RIGHT, fontName="Helvetica-Bold")
S_BOLD = ParagraphStyle("bold", parent=_BASE, fontName="Helvetica-Bold")
S_SELLER = ParagraphStyle("seller", parent=_BASE, fontName="Helvetica-Bold", fontSize=13, leading=17)
S_TITLE = ParagraphStyle("title", parent=_BASE, fontName="Helvetica-Bold", fontSize=20, leading=24)
S_HEAD = ParagraphStyle("head", parent=_BASE, fontName="Helvetica-Bold", fontSize=8.5, textColor=MUTED)
S_HEAD_RIGHT = ParagraphStyle("headright", parent=S_HEAD, alignment=TA_RIGHT)
S_NOTICE = ParagraphStyle("notice", parent=_BASE, fontName="Helvetica-Bold", fontSize=10.5, leading=14)


def _p(text: str, style: ParagraphStyle = S_TEXT) -> Paragraph:
    """Paragraph from plain text (escaped; newlines become line breaks)."""
    return Paragraph(escape(text or "").replace("\n", "<br/>"), style)


def _date(d: date) -> str:
    return f"{d:%d-%m-%Y}"


def _rate(rate_bp: int) -> str:
    if rate_bp % 100 == 0:
        return f"{rate_bp // 100}%"
    return f"{rate_bp / 100:.2f}".replace(".", ",") + "%"


def _address(name: str, line: str, postal: str, city: str, country: str) -> list[str]:
    rows = [name, line, " ".join(x for x in (postal, city) if x)]
    if country and country.upper() != "NL":
        rows.append(country.upper())
    return [r for r in rows if r]


class _NumberedCanvas(canvas.Canvas):
    """Canvas that knows the page count, so the footer can say 'Pagina 1 van 2'."""

    def __init__(self, *args, footer_lines: list[str] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved: list[dict] = []
        self._footer_lines = footer_lines or []

    def showPage(self):  # noqa: N802 - ReportLab API
        self._saved.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved)
        for state in self._saved:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total: int) -> None:
        self.saveState()
        self.setStrokeColor(RULE)
        self.setLineWidth(0.5)
        self.line(MARGIN_X, 21 * mm, PAGE_W - MARGIN_X, 21 * mm)
        self.setFont("Helvetica", 7.5)
        self.setFillColor(MUTED)
        y = 17 * mm
        for text in self._footer_lines:
            self.drawString(MARGIN_X, y, text)
            y -= 9.5
        self.drawRightString(PAGE_W - MARGIN_X, 17 * mm, f"Pagina {self._pageNumber} van {total}")
        self.restoreState()


def _footer_lines(
    name: str, kvk: str, btw_id: str, iban: str, email: str | None, phone: str | None
) -> list[str]:
    first = " | ".join(x for x in (name, f"KvK {kvk}" if kvk else "", f"BTW-id {btw_id}" if btw_id else "") if x)
    second = " | ".join(
        x for x in (f"IBAN {iban}" if iban else "", email or "", f"Tel. {phone}" if phone else "") if x
    )
    return [t for t in (first, second) if t]


def _build(story: list[Flowable], footer: list[str], title: str, author: str) -> bytes:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN_X,
        rightMargin=MARGIN_X,
        topMargin=MARGIN_TOP,
        bottomMargin=MARGIN_BOTTOM,
        title=title,
        author=author,
        invariant=1,  # fixed creation date and id: identical input gives identical bytes
    )
    doc.build(story, canvasmaker=lambda *a, **kw: _NumberedCanvas(*a, footer_lines=footer, **kw))
    return buffer.getvalue()


def _header(seller_lines: list[str], title: str, subtitle: str | None = None) -> Table:
    left = [_p(seller_lines[0], S_SELLER)] + [_p(line, S_SMALL) for line in seller_lines[1:]]
    right = [_p(title, ParagraphStyle("t", parent=S_TITLE, alignment=TA_RIGHT))]
    if subtitle:
        right.append(_p(subtitle, ParagraphStyle("st", parent=S_NOTICE, alignment=TA_RIGHT, textColor=MUTED)))
    table = Table([[left, right]], colWidths=[CONTENT_W * 0.55, CONTENT_W * 0.45])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _two_columns(left: list[Flowable], right: list[Flowable]) -> Table:
    table = Table([[left, right]], colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _facts(rows: list[tuple[str, str]]) -> Table:
    data = [[_p(label, S_SMALL), _p(value, S_BOLD)] for label, value in rows]
    table = Table(data, colWidths=[CONTENT_W * 0.2, CONTENT_W * 0.3])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 1),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 1)]))
    return table


def render_invoice_pdf(doc: InvoiceDocument) -> bytes:
    """A4 PDF with all art. 35a Wet OB fields. A concept is marked CONCEPT and has no number."""
    credit = doc.kind == CREDIT_NOTE
    title = "Creditnota" if credit else "Factuur"
    seller = _address(doc.seller_name, doc.seller_address_line, doc.seller_postal_code,
                      doc.seller_city, doc.seller_country)
    if doc.seller_email:
        seller.append(doc.seller_email)
    if doc.seller_phone:
        seller.append(doc.seller_phone)

    story: list[Flowable] = [
        _header(seller, title, "CONCEPT - nog niet definitief" if doc.is_concept else None),
        Spacer(1, 12 * mm),
    ]

    buyer = [_p(line, S_BOLD if i == 0 else S_TEXT) for i, line in enumerate(
        _address(doc.buyer_name, doc.buyer_address_line, doc.buyer_postal_code, doc.buyer_city, doc.buyer_country))]
    if doc.buyer_btw_number:
        buyer.append(_p(f"BTW-nummer: {doc.buyer_btw_number}", S_SMALL))
    if doc.buyer_kvk:
        buyer.append(_p(f"KvK-nummer: {doc.buyer_kvk}", S_SMALL))

    facts = [(f"{title}nummer", doc.number or "(volgt na definitief maken)"),
             (f"{title}datum", _date(doc.invoice_date))]
    if doc.service_date and doc.service_date != doc.invoice_date:
        facts.append(("Leverdatum", _date(doc.service_date)))
    if not credit:
        term = "direct betalen" if doc.payment_term_days == 0 else f"{doc.payment_term_days} dagen"
        facts.append(("Vervaldatum", f"{_date(doc.due_date)} ({term})"))
    if doc.reference:
        facts.append(("Uw referentie", doc.reference))
    story += [_two_columns(buyer, [_facts(facts)]), Spacer(1, 8 * mm)]

    if credit:
        original = ""
        if doc.credited_number:
            original = f"Creditnota bij factuur {doc.credited_number}"
            if doc.credited_date:
                original += f" van {_date(doc.credited_date)}"
        story.append(_p(original, S_NOTICE) if original else Spacer(1, 0))
        story.append(_p("Creditnota - u ontvangt dit bedrag terug / dit bedrag wordt verrekend.", S_TEXT))
        story.append(Spacer(1, 5 * mm))

    head = [_p("Omschrijving", S_HEAD), _p("Aantal", S_HEAD_RIGHT), _p("Prijs excl. BTW", S_HEAD_RIGHT),
            _p("BTW", S_HEAD_RIGHT), _p("Bedrag excl. BTW", S_HEAD_RIGHT)]
    rows = [head]
    for line in doc.lines:
        quantity = format_quantity(line.quantity_milli) + (f" {line.unit}" if line.unit else "")
        rows.append([_p(line.description), _p(quantity, S_RIGHT), _p(format_euro(line.unit_price_cents), S_RIGHT),
                     _p(_rate(line.rate_bp), S_RIGHT), _p(format_euro(line.line_excl_cents), S_RIGHT)])
    widths = [CONTENT_W * f for f in (0.38, 0.14, 0.18, 0.09, 0.21)]
    lines_table = Table(rows, colWidths=widths, repeatRows=1)
    lines_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
        ("LINEBELOW", (0, 0), (-1, 0), 0.5, RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [lines_table, Spacer(1, 5 * mm)]

    total_rows = [[_p("Totaal excl. BTW"), _p(format_euro(doc.total_excl_cents), S_RIGHT)]]
    for group in doc.vat_groups:
        total_rows.append([_p(f"BTW {_rate(group.rate_bp)} over {format_euro(group.base_cents)}"),
                           _p(format_euro(group.vat_cents), S_RIGHT)])
    total_rows.append([_p("Totaal incl. BTW", S_BOLD), _p(format_euro(doc.total_incl_cents), S_RIGHT_BOLD)])
    totals = Table(total_rows, colWidths=[CONTENT_W * 0.30, CONTENT_W * 0.18], hAlign="RIGHT")
    totals.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, INK),
    ]))
    closing: list[Flowable] = [totals, Spacer(1, 6 * mm)]  # kept together: totals never stand alone
    if credit:
        closing.append(_p("Dit bedrag wordt in mindering gebracht op wat u ons nog verschuldigd bent. "
                          "Is er niets openstaand, dan ontvangt u het bedrag terug.", S_TEXT))
    else:
        closing.append(_p(f"Wij ontvangen het bedrag graag vóór {_date(doc.due_date)} op {doc.seller_iban} "
                          f"onder vermelding van {doc.number or 'het factuurnummer'}.", S_TEXT))
    if doc.note:
        closing += [Spacer(1, 4 * mm), _p(doc.note, S_TEXT)]
    story.append(KeepTogether(closing))

    footer = _footer_lines(doc.seller_name, doc.seller_kvk, doc.seller_btw_id, doc.seller_iban,
                           doc.seller_email, doc.seller_phone)
    label = f"{title} {doc.number}".strip() if doc.number else f"{title} (concept)"
    return _build(story, footer, label, doc.seller_name)


def render_reminder_pdf(doc: ReminderDocument) -> bytes:
    """A4 letter: seller, klant, title, the facts of the invoice and the proposed text."""
    seller = _address(doc.seller_name, doc.seller_address_line, doc.seller_postal_code,
                      doc.seller_city, doc.seller_country)
    if doc.seller_email:
        seller.append(doc.seller_email)
    if doc.seller_phone:
        seller.append(doc.seller_phone)
    buyer = [_p(line, S_BOLD if i == 0 else S_TEXT) for i, line in enumerate(
        _address(doc.buyer_name, doc.buyer_address_line, doc.buyer_postal_code, doc.buyer_city, doc.buyer_country))]

    story: list[Flowable] = [
        _header(seller, doc.title),
        Spacer(1, 12 * mm),
        _two_columns(buyer, [_facts([("Datum", _date(doc.reminder_date)),
                                     ("Factuurnummer", doc.invoice_number)])]),
        Spacer(1, 8 * mm),
    ]
    summary = Table(
        [
            [_p("Factuurdatum", S_SMALL), _p(_date(doc.invoice_date), S_TEXT)],
            [_p("Oorspronkelijke vervaldatum", S_SMALL), _p(_date(doc.due_date), S_TEXT)],
            [_p("Openstaand bedrag", S_SMALL), _p(format_euro(doc.open_cents), S_BOLD)],
            [_p("Betalen vóór", S_SMALL), _p(_date(doc.new_due_date), S_BOLD)],
        ],
        colWidths=[CONTENT_W * 0.35, CONTENT_W * 0.35],
        hAlign="LEFT",
    )
    summary.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), HEAD_BG), ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    story += [summary, Spacer(1, 6 * mm)]
    for block in (b for b in doc.body_text.split("\n\n") if b.strip()):
        story += [_p(block.strip(), S_TEXT), Spacer(1, 3 * mm)]

    footer = _footer_lines(doc.seller_name, doc.seller_kvk, doc.seller_btw_id, doc.seller_iban,
                           doc.seller_email, doc.seller_phone)
    return _build(story, footer, f"{doc.title} {doc.invoice_number}", doc.seller_name)
