"""Deterministic duplicate keys for bank transactions (pure functions, no DB).

dedupe_key = sha256(bankrekening_id | booking_date | amount_cents | counterparty IBAN |
                    end_to_end_id or bank_reference or "" | normalised description)
`occurrence` numbers identical keys within one file (1, 2, ...), so two genuinely
identical payments in one file are both kept.
"""

import hashlib
import re
from collections import Counter
from collections.abc import Iterable

from app.domain.bank.iban import normalize_iban
from app.domain.bank.types import ParsedStatement, ParsedTransaction


def normalize_text(value: str | None) -> str:
    """Trimmed, casefolded, whitespace collapsed."""
    return re.sub(r"\s+", " ", value or "").strip().casefold()


def dedupe_key(bank_account_id: int, tx: ParsedTransaction) -> str:
    reference = tx.end_to_end_id or tx.bank_reference or ""
    parts = (
        str(bank_account_id),
        tx.booking_date.isoformat(),
        str(tx.amount_cents),
        normalize_iban(tx.counterparty_iban),
        normalize_text(reference),
        normalize_text(tx.description),
    )
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def compute_keys(
    bank_account_id: int, parsed: ParsedStatement | Iterable[ParsedTransaction]
) -> list[tuple[str, int]]:
    """(dedupe_key, occurrence) per transaction, in file order."""
    transactions = parsed.transactions if isinstance(parsed, ParsedStatement) else parsed
    seen: Counter[str] = Counter()
    result = []
    for tx in transactions:
        key = dedupe_key(bank_account_id, tx)
        seen[key] += 1
        result.append((key, seen[key]))
    return result
