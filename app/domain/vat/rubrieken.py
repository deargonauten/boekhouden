"""Catalogue of btw-aangifte rubrieken (pure). Plain-Dutch labels for the UI."""

SALES_RUBRIEKEN: dict[str, str] = {
    "1a": "Omzet met 21% btw",
    "1b": "Omzet met 9% btw",
    "1c": "Omzet met een ander btw-tarief",
    "1d": "Privégebruik",
    "1e": "Omzet met 0% of waarbij de klant de btw afrekent",
    "3a": "Verkoop buiten de EU",
    "3b": "Verkoop binnen de EU",
    "3c": "Installatie en afstandsverkopen binnen de EU",
}

PURCHASE_RUBRIEKEN: dict[str, str] = {
    "2a": "Btw verlegd naar jou",
    "4a": "Inkoop van buiten de EU",
    "4b": "Inkoop uit de EU",
    "5b": "Voorbelasting (btw die je terugkrijgt)",
}

# These purchase rubrieken also create voorbelasting in 5b (for the BTW-aangifte feature;
# no logic here).
ALSO_INPUT_VAT = {"2a", "4a", "4b"}


def rubriek_label(side: str, rubriek: str | None) -> str | None:
    """Plain label for a rubriek on 'sales' or 'purchase' side; None when empty/unknown."""
    catalogue = SALES_RUBRIEKEN if side == "sales" else PURCHASE_RUBRIEKEN
    return catalogue.get(rubriek) if rubriek else None


def suggest_rubrieken(rate_bp: int) -> tuple[str | None, str | None]:
    """(sales, purchase) rubriek suggested for a new code with this rate."""
    if rate_bp == 2100:
        return "1a", "5b"
    if rate_bp == 900:
        return "1b", "5b"
    if rate_bp == 0:
        return "1e", None
    return "1c", "5b"
