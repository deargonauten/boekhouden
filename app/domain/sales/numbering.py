"""Gapless invoice numbers `YYYY-NNNN`, one series per year for invoices and creditnota's."""

from sqlalchemy import text
from sqlalchemy.orm import Session


def format_number(year: int, seq: int) -> str:
    return f"{year}-{seq:04d}"


def next_number(session: Session, year: int) -> tuple[int, str]:
    """Increment the counter of `year` and return (seq, number).

    Must run inside the caller's locked transaction (see `service._open_transaction`) and
    inside a savepoint that is rolled back on any later failure, so no number is lost.
    """
    seq = session.execute(
        text(
            "INSERT INTO sales_number_counter(year, last_number) VALUES (:y, 1) "
            "ON CONFLICT(year) DO UPDATE SET last_number = last_number + 1 "
            "RETURNING last_number"
        ),
        {"y": year},
    ).scalar_one()
    return seq, format_number(year, seq)
