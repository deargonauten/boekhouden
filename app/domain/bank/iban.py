"""IBAN normalisation and validation (country, length, mod-97)."""

import re

# Official IBAN lengths for the countries a Dutch business is likely to meet.
_LENGTHS = {
    "AD": 24, "AT": 20, "BE": 16, "BG": 22, "CH": 21, "CY": 28, "CZ": 24, "DE": 22,
    "DK": 18, "EE": 20, "ES": 24, "FI": 18, "FR": 27, "GB": 22, "GI": 23, "GR": 27,
    "HR": 21, "HU": 28, "IE": 22, "IS": 26, "IT": 27, "LI": 21, "LT": 20, "LU": 20,
    "LV": 21, "MC": 27, "MT": 31, "NL": 18, "NO": 15, "PL": 28, "PT": 25, "RO": 24,
    "SE": 24, "SI": 19, "SK": 24, "SM": 27, "TR": 26,
}  # fmt: skip

_BANK_CODES = {"INGB": "ing", "RABO": "rabobank", "ABNA": "abn_amro", "BUNQ": "bunq"}

_CANDIDATE = re.compile(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}")


def normalize_iban(value: str | None) -> str:
    """Uppercase, no spaces/dashes. Empty string for None."""
    return re.sub(r"[\s\-]", "", value or "").upper()


def is_valid_iban(value: str | None) -> bool:
    iban = normalize_iban(value)
    if not _CANDIDATE.fullmatch(iban):
        return False
    expected = _LENGTHS.get(iban[:2])
    if expected is not None and len(iban) != expected:
        return False
    rearranged = iban[4:] + iban[:4]
    number = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(number) % 97 == 1


def bank_from_iban(iban: str | None) -> str | None:
    """Guess the bank key from the bank code of a Dutch IBAN (NL91ABNA...)."""
    n = normalize_iban(iban)
    if n.startswith("NL") and len(n) >= 8:
        return _BANK_CODES.get(n[4:8])
    return None


def find_iban(text: str | None) -> str | None:
    """First valid IBAN inside free text (spaces allowed), normalised; None if there is none."""
    if not text:
        return None
    upper = text.upper()
    # Candidates: country+check digits at a word boundary, followed by up to 30 alphanumerics
    # that may be grouped with single spaces.
    for m in re.finditer(r"(?<![A-Z0-9])[A-Z]{2}\d{2}", upper):
        tail = upper[m.start() :]
        compact = ""
        for ch_idx, ch in enumerate(tail):
            if ch.isalnum():
                compact += ch
            elif ch == " " and ch_idx + 1 < len(tail) and tail[ch_idx + 1].isalnum():
                continue
            else:
                break
            if len(compact) >= 34:
                break
        for end in range(min(len(compact), 34), 14, -1):
            if is_valid_iban(compact[:end]):
                return compact[:end]
    return None
