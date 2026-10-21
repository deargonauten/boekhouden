import time

import pytest

import app.domain.relations as relations
from app.domain.errors import RelationError
from app.domain.relations import (
    ContactInput,
    create_contact,
    get_contact,
    list_contacts,
    set_contact_active,
    update_contact,
)


def mk(session, name="Jansen BV", **kw):
    kw.setdefault("is_supplier", True)
    return create_contact(session, ContactInput(name=name, **kw))


def test_create_and_get(session):
    c = mk(
        session,
        name=" Jansen & Zn. B.V. ",
        kvk="1234 5678",
        btw_number="nl123456789b01",
        iban="nl91 abna 0417 1643 00",
        city="Amsterdam",
        email="",
    )
    session.commit()
    got = get_contact(session, c.id)
    assert got.name == "Jansen & Zn. B.V."
    assert got.name_key == "jansen en zn"
    assert got.kvk == "12345678"
    assert got.btw_number == "NL123456789B01"
    assert got.iban == "NL91ABNA0417164300"
    assert got.email is None  # empty string stored as NULL
    assert got.country == "NL"
    assert got.is_active is True
    assert got.created_at is not None and got.updated_at is not None


def test_create_does_not_commit(session, engine):
    from sqlalchemy.orm import Session

    mk(session)
    session.rollback()
    assert list_contacts(session) == []


def test_validation_error_collects_all(session):
    with pytest.raises(RelationError) as exc:
        create_contact(session, ContactInput(name="", kvk="1"))
    assert "NAME_REQUIRED" in exc.value.codes and "INVALID_KVK" in exc.value.codes


def test_get_unknown(session):
    with pytest.raises(RelationError) as exc:
        get_contact(session, 999)
    assert exc.value.code == "CONTACT_NOT_FOUND"


def test_update_changes_fields_name_key_and_updated_at(session):
    c = mk(session, name="Oud Bedrijf", kvk="12345678")
    session.commit()
    before = c.updated_at
    time.sleep(0.01)
    u = update_contact(
        session,
        c.id,
        ContactInput(name="Nieuw & Co", is_customer=True, is_supplier=False, kvk="", city="Utrecht"),
    )
    session.commit()
    assert u.name == "Nieuw & Co"
    assert u.name_key == "nieuw en co"
    assert u.kvk is None
    assert u.is_customer and not u.is_supplier
    assert u.city == "Utrecht"
    assert u.updated_at > before
    assert u.created_at == c.created_at


def test_update_unknown(session):
    with pytest.raises(RelationError) as exc:
        update_contact(session, 5, ContactInput(name="X", is_customer=True))
    assert exc.value.code == "CONTACT_NOT_FOUND"


def test_update_keeps_own_identifiers(session):
    c = mk(session, kvk="12345678")
    update_contact(session, c.id, ContactInput(name="Anders", is_supplier=True, kvk="12345678"))


@pytest.mark.parametrize(
    "field,v1,v2,code,label",
    [
        ("kvk", "12345678", "1234 5678", "DUPLICATE_KVK", "KvK-nummer"),
        ("btw_number", "NL123456789B01", "nl 123456789 b01", "DUPLICATE_BTW_NUMBER", "btw-nummer"),
        ("iban", "NL91ABNA0417164300", "NL91 ABNA 0417 1643 00", "DUPLICATE_IBAN", "IBAN"),
    ],
)
def test_duplicates(session, field, v1, v2, code, label):
    first = mk(session, name="Eerste", **{field: v1})
    session.commit()
    with pytest.raises(RelationError) as exc:
        mk(session, name="Tweede", **{field: v2})
    assert exc.value.code == code
    assert exc.value.is_duplicate
    assert exc.value.message == (
        f"Er bestaat al een relatie met dit {label}: Eerste. "
        "Open die relatie in plaats van een nieuwe aan te maken."
    )
    # Session still usable and nothing half-written.
    assert [c.name for c in list_contacts(session)] == ["Eerste"]

    # Also on edit, and against an archived contact.
    other = mk(session, name="Derde")
    set_contact_active(session, first.id, False)
    with pytest.raises(RelationError) as exc:
        update_contact(session, other.id, ContactInput(name="Derde", is_supplier=True, **{field: v2}))
    assert exc.value.code == code
    assert "Eerste" in exc.value.message


def test_duplicates_collected(session):
    mk(session, name="A", kvk="12345678", iban="NL91ABNA0417164300")
    with pytest.raises(RelationError) as exc:
        mk(session, name="B", kvk="12345678", iban="NL91ABNA0417164300")
    assert set(exc.value.codes) == {"DUPLICATE_KVK", "DUPLICATE_IBAN"}


def test_unique_index_backstop(session):
    """If the explicit check is bypassed, the IntegrityError maps to a duplicate error."""
    from app.domain.relations import service

    mk(session, name="A", kvk="12345678")
    session.commit()
    original = service._find_duplicates
    service._find_duplicates = lambda *a, **k: []
    try:
        with pytest.raises(RelationError) as exc:
            mk(session, name="B", kvk="12345678")
    finally:
        service._find_duplicates = original
    assert exc.value.code == "DUPLICATE_KVK"
    assert [c.name for c in list_contacts(session)] == ["A"]


def test_list_sorted_and_filters(session):
    mk(session, name="Zeger", is_supplier=True)
    mk(session, name="Anna", is_supplier=False, is_customer=True, city="Utrecht")
    mk(session, name="Bert", is_supplier=True, is_customer=True, kvk="11111111")
    mk(session, name="Café Del", is_supplier=True, btw_number="NL000000001B01", iban="NL91ABNA0417164300")
    names = lambda **kw: [c.name for c in list_contacts(session, **kw)]  # noqa: E731
    assert names() == ["Anna", "Bert", "Café Del", "Zeger"]
    assert names(role="customer") == ["Anna", "Bert"]
    assert names(role="supplier") == ["Bert", "Café Del", "Zeger"]
    assert names(q="utrecht") == ["Anna"]
    assert names(q="ZEG") == ["Zeger"]
    assert names(q="1111") == ["Bert"]
    assert names(q="nl000000001") == ["Café Del"]
    assert names(q="NL91 ABNA") == ["Café Del"]
    assert names(q="nope") == []
    assert names(role="customer", q="bert") == ["Bert"]


def test_archive_restore(session):
    c = mk(session, name="Oud")
    mk(session, name="Nieuw")
    session.commit()
    before = c.updated_at
    time.sleep(0.01)
    set_contact_active(session, c.id, False)
    session.commit()
    assert get_contact(session, c.id).is_active is False
    assert get_contact(session, c.id).updated_at > before
    assert [x.name for x in list_contacts(session)] == ["Nieuw"]
    assert [x.name for x in list_contacts(session, include_archived=True)] == ["Nieuw", "Oud"]
    set_contact_active(session, c.id, True)
    assert [x.name for x in list_contacts(session)] == ["Nieuw", "Oud"]
    with pytest.raises(RelationError):
        set_contact_active(session, 999, False)


def test_no_delete_api():
    from app.domain.relations import service

    for mod in (relations, service):
        assert not any("delete" in n.lower() or "remove" in n.lower() for n in dir(mod))


def test_list_contacts_page_slices_and_clamps(session):
    from app.domain.relations import list_contacts_page

    for n in range(5):
        mk(session, name=f"Naam {n}", is_supplier=True)
    page = list_contacts_page(session, per_page=2, page=2)
    assert [c.name for c in page.items] == ["Naam 2", "Naam 3"]
    assert (page.total, page.page, page.per_page) == (5, 2, 2)
    assert list_contacts_page(session, per_page=2, page=0).page == 1
    last = list_contacts_page(session, per_page=2, page=99)
    assert last.page == 3 and [c.name for c in last.items] == ["Naam 4"]
    empty = list_contacts_page(session, q="nope", per_page=2, page=5)
    assert empty.items == [] and empty.total == 0 and empty.page == 1
    assert list_contacts_page(session, q="naam 1").total == 1
