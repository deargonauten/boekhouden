"""STUB owned by builder A, to be REPLACED by builder B (real layout, art. 35a fields).

Only exists so that `service.finalize` and `reminders.create_reminder` can run before the real
renderer is there. The signatures below are the contract; the output is a trivial but valid
one-page PDF with just the number (or title). Do not put layout in here.
"""

from io import BytesIO

from reportlab.pdfgen import canvas

from app.domain.sales.types import InvoiceDocument, ReminderDocument


def _simple_pdf(text: str) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, invariant=1)  # invariant: identical input -> identical bytes
    pdf.drawString(72, 770, text)
    pdf.save()
    return buffer.getvalue()


def render_invoice_pdf(doc: InvoiceDocument) -> bytes:
    title = "Creditnota" if doc.kind == "credit_note" else "Factuur"
    return _simple_pdf(f"{title} {doc.number or '(concept)'}")


def render_reminder_pdf(doc: ReminderDocument) -> bytes:
    return _simple_pdf(f"{doc.title} {doc.invoice_number}")
