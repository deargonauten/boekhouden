"""Helpers to book realistic btw entries in the vat tests."""

from datetime import date

from sqlalchemy import select

from app.domain.ledger import NewEntry, NewLine, create_fiscal_year, post_entry, reverse_entry
from app.models import Account, Journal

Q3 = (date(2026, 7, 1), date(2026, 9, 30))
DAY = date(2026, 8, 15)


class Book:
    """Posts entries by account code. Lines are (account_code, debit, credit[, vat_code])."""

    def __init__(self, session, year=2026):
        self.s = session
        create_fiscal_year(session, year)
        session.flush()

    def acc(self, code):
        return self.s.scalar(select(Account.id).where(Account.code == code))

    def post(self, lines, day=DAY, desc="Test", journal="MEM", kind="normal"):
        jid = self.s.scalar(select(Journal.id).where(Journal.code == journal))
        new = [
            NewLine(self.acc(l[0]), debit_cents=l[1], credit_cents=l[2], vat_code=l[3] if len(l) > 3 else None)
            for l in lines
        ]
        e = post_entry(self.s, NewEntry(journal_id=jid, booking_date=day, description=desc, lines=new, kind=kind))
        self.s.flush()
        return e

    def sale(self, net, vat, *, code="NL_21", revenue="8000", btw="3100", day=DAY, desc="Verkoop"):
        lines = [("1210", net + vat, 0), (revenue, 0, net, code)]
        if vat:
            lines.append((btw, 0, vat))
        return self.post(lines, day=day, desc=desc, journal="VK")

    def credit_note(self, net, vat, *, code="NL_21", revenue="8000", btw="3100", day=DAY):
        lines = [("1210", 0, net + vat), (revenue, net, 0, code)]
        if vat:
            lines.append((btw, vat, 0))
        return self.post(lines, day=day, desc="Creditnota", journal="VK")

    def purchase(self, net, vat, *, code="NL_21", expense="4000", day=DAY):
        lines = [(expense, net, 0, code), ("2000", 0, net + vat)]
        if vat:
            lines.insert(1, ("1400", vat, 0))
        return self.post(lines, day=day, desc="Inkoop", journal="IK")

    def reverse(self, entry, day=DAY):
        e = reverse_entry(self.s, entry.id, booking_date=day)
        self.s.flush()
        return e


def rubriek(report, name):
    return next(l for l in report.lines if l.rubriek == name)


def codes(report):
    return [w.code for w in report.warnings]


def insert_return(session, year, kind, number, total=0):
    """Insert a filed return row directly (bypasses file_vat_return) for settings tests."""
    from datetime import datetime

    from app.domain.vat.periods import VatPeriod, period_range
    from app.models import VatReturn

    start, end = period_range(VatPeriod(year, kind, number))
    session.add(VatReturn(
        year=year, kind=kind, number=number, start_date=start, end_date=end, status="ingediend",
        filed_on=end, filed_at=datetime(2026, 1, 1), snapshot_json="{}", total_cents=total,
    ))
    session.flush()


def make_contact(session, name="Klant BV", country="DE", btw="DE123456789", customer=True):
    from datetime import datetime

    from app.domain.relations.validation import normalize_name
    from app.models import Contact

    now = datetime(2026, 1, 1)
    c = Contact(
        name=name, name_key=normalize_name(name), is_customer=customer, is_supplier=not customer,
        btw_number=btw, country=country, is_active=True, created_at=now, updated_at=now,
    )
    session.add(c)
    session.flush()
    return c


def link_invoice(session, entry, contact, *, btw="DE123456789", country="DE", name="Klant BV"):
    """A sales invoice row pointing at the entry, with the buyer snapshot as at finalize."""
    from datetime import datetime

    from app.models import SalesInvoice

    inv = SalesInvoice(
        contact_id=contact.id, invoice_date=entry.booking_date, payment_term_days=30,
        due_date=entry.booking_date, buyer_name=name, buyer_btw_number=btw, buyer_country=country,
        journal_entry_id=entry.id, created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1),
    )
    session.add(inv)
    session.flush()
    return inv
