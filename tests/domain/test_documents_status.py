import pytest

from app.domain.documents.status import (
    ALLOWED_TRANSITIONS,
    DOCUMENT_SOURCES,
    DOCUMENT_STATUSES,
    STATUS_LABELS,
    DocumentStatus,
    check_transition,
)
from app.domain.errors import DocumentError, InvalidStatusTransitionError


def test_constants():
    assert DOCUMENT_STATUSES == ("nieuw", "herkend", "geboekt")
    assert DOCUMENT_SOURCES == ("upload", "email")
    assert DocumentStatus.NIEUW == "nieuw"
    assert DocumentStatus.HERKEND == "herkend"
    assert DocumentStatus.GEBOEKT == "geboekt"
    assert STATUS_LABELS == {"nieuw": "Nieuw", "herkend": "Herkend", "geboekt": "Geboekt"}


def test_transition_table():
    assert ALLOWED_TRANSITIONS == {
        "nieuw": {"herkend", "geboekt"},
        "herkend": {"geboekt"},
        "geboekt": set(),
    }


@pytest.mark.parametrize(
    "old,new", [("nieuw", "herkend"), ("nieuw", "geboekt"), ("herkend", "geboekt")]
)
def test_allowed(old, new):
    check_transition(old, new)


@pytest.mark.parametrize(
    "old,new",
    [
        ("herkend", "nieuw"),
        ("geboekt", "nieuw"),
        ("geboekt", "herkend"),
        ("geboekt", "geboekt"),
        ("nieuw", "nieuw"),
        ("herkend", "herkend"),
        ("nieuw", "onbekend"),
        ("onbekend", "geboekt"),
    ],
)
def test_illegal(old, new):
    with pytest.raises(InvalidStatusTransitionError) as exc:
        check_transition(old, new)
    assert exc.value.code == "INVALID_STATUS_TRANSITION"
    assert isinstance(exc.value, DocumentError)


def test_message_names_both_statuses_and_gives_hint():
    with pytest.raises(InvalidStatusTransitionError) as exc:
        check_transition("geboekt", "herkend")
    msg = exc.value.message
    assert msg.startswith("Dit document kan niet van Geboekt naar Herkend worden gezet.")
    assert "stornoboeking" in msg
