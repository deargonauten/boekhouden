"""Rubriek mapping for the seeded btw-codes (plain data; imported by migration 0007).

(sales_rubriek, purchase_rubriek) per code; None = not part of the btw-aangifte.
"""

SEED_VAT_ORDER: list[str] = [
    "GEEN",
    "NL_21",
    "NL_9",
    "NL_0",
    "VERLEGD",
    "EU_GOEDEREN",
    "EU_DIENSTEN",
    "EXPORT",
]

SEED_VAT_RUBRIEKEN: dict[str, tuple[str | None, str | None]] = {
    "GEEN": (None, None),
    "NL_21": ("1a", "5b"),
    "NL_9": ("1b", "5b"),
    "NL_0": ("1e", None),
    "VERLEGD": ("1e", "2a"),
    "EU_GOEDEREN": ("3b", "4b"),
    "EU_DIENSTEN": ("3b", "4b"),
    "EXPORT": ("3a", "4a"),
}
