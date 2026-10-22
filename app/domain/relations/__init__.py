"""Public relations API (klanten en leveranciers)."""

from app.domain.errors import RelationError
from app.domain.relations.matching import (
    ExtractedContact,
    MatchResult,
    match_or_create_contact,
)
from app.domain.relations.service import (
    ContactPage,
    create_contact,
    get_contact,
    list_contacts,
    list_contacts_page,
    set_contact_active,
    update_contact,
)
from app.domain.relations.validation import (
    ContactInput,
    NormalizedContact,
    format_iban,
    is_valid_btw_number,
    is_valid_iban,
    is_valid_kvk,
    normalize_btw_number,
    normalize_email,
    normalize_iban,
    normalize_kvk,
    normalize_name,
    validate_btw_number,
    validate_contact_input,
    validate_email,
    validate_iban,
    validate_kvk,
    validate_payment_term,
)
