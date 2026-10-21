"""Pure status model of a document in the inbox."""

from app.domain.errors import InvalidStatusTransitionError

NIEUW = "nieuw"
HERKEND = "herkend"
GEBOEKT = "geboekt"

DOCUMENT_STATUSES: tuple[str, ...] = (NIEUW, HERKEND, GEBOEKT)
DOCUMENT_SOURCES: tuple[str, ...] = ("upload", "email")


class DocumentStatus:
    NIEUW = NIEUW
    HERKEND = HERKEND
    GEBOEKT = GEBOEKT


STATUS_LABELS: dict[str, str] = {NIEUW: "Nieuw", HERKEND: "Herkend", GEBOEKT: "Geboekt"}

# geboekt is final: corrections are a storno on the booking, never reopening.
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    NIEUW: frozenset({HERKEND, GEBOEKT}),
    HERKEND: frozenset({GEBOEKT}),
    GEBOEKT: frozenset(),
}


def check_transition(current: str, new: str) -> None:
    """Raise InvalidStatusTransitionError unless current -> new is allowed."""
    if new in ALLOWED_TRANSITIONS.get(current, frozenset()):
        return
    old_label = STATUS_LABELS.get(current, current)
    new_label = STATUS_LABELS.get(new, new)
    raise InvalidStatusTransitionError(
        f"Dit document kan niet van {old_label} naar {new_label} worden gezet. "
        "Een geboekt document blijft geboekt; gebruik een stornoboeking "
        "als er iets niet klopt."
    )
