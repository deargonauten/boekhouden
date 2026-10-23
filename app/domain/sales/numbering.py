"""Gapless invoice numbers `<jaar><scheidingsteken><volgnummer>`, shared by invoices and creditnota's.

The user chooses the separator, the number of digits and whether the volgnummer starts again
every year or runs on over the years (setting `invoice_numbering`; default `YYYY-NNNN` per year).
"""

from dataclasses import dataclass

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.domain.errors import LedgerError
from app.models.sales import InvoiceNumbering, SalesInvoice

SEPARATORS = ("-", ".", "/", "")
CONTINUOUS_KEY = 0  # counter row used when the volgnummer runs on over the years
INVALID_NUMBERING = "INVALID_NUMBERING"


class NumberingError(LedgerError):
    code = INVALID_NUMBERING


@dataclass(frozen=True)
class NumberingConfig:
    separator: str = "-"
    digits: int = 4
    continuous: bool = False


def format_number(year: int, seq: int, config: NumberingConfig = NumberingConfig()) -> str:
    return f"{year}{config.separator}{seq:0{config.digits}d}"


def get_config(session: Session) -> NumberingConfig:
    row = session.get(InvoiceNumbering, 1)
    if row is None:
        return NumberingConfig()
    return NumberingConfig(row.separator, row.digits, bool(row.continuous))


def _key(config: NumberingConfig, year: int) -> int:
    return CONTINUOUS_KEY if config.continuous else year


def _highest_used(session: Session, config: NumberingConfig, year: int) -> int:
    """Highest volgnummer already on a definitief document in the series that `year` belongs to."""
    q = select(func.coalesce(func.max(SalesInvoice.number_seq), 0))
    if not config.continuous:
        q = q.where(SalesInvoice.number_year == year)
    return session.scalar(q)


def _last_number(session: Session, config: NumberingConfig, year: int) -> int:
    row = session.execute(
        text("SELECT last_number FROM sales_number_counter WHERE year = :k"), {"k": _key(config, year)}
    ).scalar()
    return row if row is not None else _highest_used(session, config, year)


def peek_next_seq(session: Session, year: int) -> int:
    """The volgnummer the next invoice of `year` will get (nothing is reserved)."""
    return _last_number(session, get_config(session), year) + 1


def save_config(
    session: Session, *, separator: str, digits: int, continuous: bool, next_seq: int, year: int
) -> NumberingConfig:
    """Store the format and set the next volgnummer. Flushes; the caller commits.

    The next volgnummer must lie above everything already used in the series, so the sequence
    stays gapless and unique.
    """
    if separator not in SEPARATORS:
        raise NumberingError("Kies een scheidingsteken uit de lijst.")
    if not 1 <= digits <= 8:
        raise NumberingError("Het volgnummer heeft 1 tot en met 8 cijfers. Vul een getal in van 1 tot 8.")
    config = NumberingConfig(separator, digits, continuous)
    used = _highest_used(session, config, year)
    if next_seq < 1 or next_seq <= used:
        raise NumberingError(
            f"Het volgende nummer moet hoger zijn dan {used}: dat nummer is al gebruikt op een "
            f"definitieve factuur. Vul {used + 1} of hoger in."
        )
    row = session.get(InvoiceNumbering, 1)
    if row is None:
        row = InvoiceNumbering(id=1)
        session.add(row)
    row.separator, row.digits, row.continuous = separator, digits, continuous
    session.execute(
        text(
            "INSERT INTO sales_number_counter(year, last_number) VALUES (:k, :n) "
            "ON CONFLICT(year) DO UPDATE SET last_number = :n"
        ),
        {"k": _key(config, year), "n": next_seq - 1},
    )
    session.flush()
    return config


def next_number(session: Session, year: int) -> tuple[int, str]:
    """Increment the counter of the series and return (seq, number).

    Must run inside the caller's locked transaction (see `service._open_transaction`) and
    inside a savepoint that is rolled back on any later failure, so no number is lost.
    """
    config = get_config(session)
    key = _key(config, year)
    # A series without counter row yet (e.g. just switched to doorlopend) continues after the highest used number.
    seed = _highest_used(session, config, year) + 1
    seq = session.execute(
        text(
            "INSERT INTO sales_number_counter(year, last_number) VALUES (:k, :seed) "
            "ON CONFLICT(year) DO UPDATE SET last_number = last_number + 1 "
            "RETURNING last_number"
        ),
        {"k": key, "seed": seed},
    ).scalar_one()
    return seq, format_number(year, seq, config)
