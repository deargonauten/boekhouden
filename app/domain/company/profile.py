"""Read-only view of the company's bedrijfsgegevens, for invoices and the btw-aangifte."""

from dataclasses import dataclass

from app.domain.relations.validation import format_iban

# (field, Dutch label) in form order
REQUIRED_FOR_INVOICE: tuple[tuple[str, str], ...] = (
    ("legal_name", "naam"),
    ("address_line", "adres"),
    ("postal_code", "postcode"),
    ("city", "plaats"),
    ("kvk", "KvK-nummer"),
    ("btw_id", "btw-id"),
    ("iban", "IBAN"),
)

_COUNTRY_NAMES = {
    "BE": "België",
    "DE": "Duitsland",
    "FR": "Frankrijk",
    "LU": "Luxemburg",
    "GB": "Verenigd Koninkrijk",
    "ES": "Spanje",
    "IT": "Italië",
}


@dataclass(frozen=True)
class CompanyProfile:
    """Plain snapshot of the stored company data; fields are None when nothing is stored."""

    legal_name: str | None = None
    trade_name: str | None = None
    legal_form: str | None = None
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    country: str | None = None
    kvk: str | None = None
    btw_id: str | None = None
    iban: str | None = None
    email: str | None = None
    phone: str | None = None

    def missing_for_invoice(self) -> list[str]:
        return [label for field, label in REQUIRED_FOR_INVOICE if not getattr(self, field)]

    @property
    def is_complete_for_invoice(self) -> bool:
        return not self.missing_for_invoice()

    @property
    def iban_display(self) -> str:
        return format_iban(self.iban)

    def address_lines(self) -> list[str]:
        """Street; "1234 AB Plaats"; country name only when not NL."""
        lines = []
        if self.address_line:
            lines.append(self.address_line)
        place = " ".join(p for p in (self.postal_code, self.city) if p)
        if place:
            lines.append(place)
        if lines and self.country and self.country != "NL":
            lines.append(_COUNTRY_NAMES.get(self.country, self.country))
        return lines
