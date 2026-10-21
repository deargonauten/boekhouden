import pytest
from sqlalchemy import func, select

from app.domain.relations import (
    ContactInput,
    ExtractedContact,
    MatchResult,
    create_contact,
    match_or_create_contact,
    set_contact_active,
)
from app.models import Contact

BTW = "NL123456789B01"
KVK = "12345678"
IBAN = "NL91ABNA0417164300"
IBAN2 = "DE89370400440532013000"


def mk(session, name="Jansen BV", **kw):
    kw.setdefault("is_supplier", True)
    return create_contact(session, ContactInput(name=name, **kw))


def count(session):
    return session.scalar(select(func.count()).select_from(Contact))


def run(session, role="supplier", **kw):
    create = kw.pop("create", True)
    return match_or_create_contact(session, ExtractedContact(**kw), role, create=create)


# --- each key in isolation ---
def test_match_on_btw(session):
    c = mk(session, btw_number=BTW)
    r = run(session, name="Anders", btw_number="nl 123456789 b01")
    assert isinstance(r, MatchResult)
    assert (r.status, r.matched_on, r.contact.id) == ("matched", "btw_number", c.id)
    assert r.candidates == () and r.warnings == ()


def test_match_on_kvk(session):
    c = mk(session, kvk=KVK)
    r = run(session, kvk="1234.5678")
    assert (r.status, r.matched_on, r.contact.id) == ("matched", "kvk", c.id)


def test_match_on_iban(session):
    c = mk(session, iban=IBAN)
    r = run(session, iban="NL91 ABNA 0417 1643 00")
    assert (r.status, r.matched_on, r.contact.id) == ("matched", "iban", c.id)


def test_match_on_name(session):
    c = mk(session, name="Jansen & Zn. B.V.")
    r = run(session, name="JANSEN en zn")
    assert (r.status, r.matched_on, r.contact.id) == ("matched", "name", c.id)


# --- priority and conflicts ---
def test_priority_btw_over_kvk_over_iban(session):
    a = mk(session, name="A", btw_number=BTW)
    b = mk(session, name="B", kvk=KVK)
    c = mk(session, name="C", iban=IBAN)
    assert run(session, btw_number=BTW, kvk=KVK, iban=IBAN).contact.id == a.id
    assert run(session, kvk=KVK, iban=IBAN).contact.id == b.id
    assert run(session, iban=IBAN).contact.id == c.id


def test_conflict_warning(session):
    a = mk(session, name="Alfa", btw_number=BTW)
    mk(session, name="Beta", iban=IBAN)
    r = run(session, btw_number=BTW, iban=IBAN)
    assert r.contact.id == a.id
    assert (
        "Het IBAN op de factuur hoort bij Beta, maar het btw-nummer hoort bij Alfa. "
        "Controleer of dit dezelfde relatie is."
    ) in r.warnings
    # Nothing from B leaked into A.
    assert a.iban is None


def test_conflict_kvk_vs_btw(session):
    mk(session, name="Alfa", btw_number=BTW)
    mk(session, name="Beta", kvk=KVK)
    r = run(session, btw_number=BTW, kvk=KVK)
    assert any("KvK-nummer op de factuur hoort bij Beta" in w for w in r.warnings)


def test_identifier_beats_name(session):
    mk(session, name="Jansen")
    b = mk(session, name="Pietersen", kvk=KVK)
    r = run(session, name="Jansen", kvk=KVK)
    assert (r.contact.id, r.matched_on) == (b.id, "kvk")


# --- archived ---
def test_archived_identifier_match_reactivates(session):
    c = mk(session, name="Oud", kvk=KVK)
    set_contact_active(session, c.id, False)
    r = run(session, kvk=KVK)
    assert r.status == "matched" and r.contact.id == c.id
    assert r.contact.is_active is True
    assert "Relatie Oud was gearchiveerd en is weer actief gemaakt." in r.warnings


def test_name_match_active_only(session):
    c = mk(session, name="Oud Bedrijf")
    set_contact_active(session, c.id, False)
    r = run(session, name="Oud Bedrijf")
    assert r.status == "created" and r.contact.id != c.id
    assert c.is_active is False


# --- ambiguous ---
def test_ambiguous_name(session):
    a = mk(session, name="Jansen BV")
    b = mk(session, name="Jansen")
    before = count(session)
    r = run(session, name="Jansen", kvk="")
    assert r.status == "ambiguous" and r.contact is None and r.matched_on is None
    assert {c.id for c in r.candidates} == {a.id, b.id}
    assert count(session) == before


def test_ambiguous_changes_nothing(session):
    a = mk(session, name="Jansen BV")
    mk(session, name="Jansen")
    run(session, name="Jansen", city="Utrecht")
    assert a.city is None


# --- invalid identifiers ---
def test_invalid_identifiers_ignored_with_warnings(session):
    r = run(session, name="Nieuw", btw_number="NL12", kvk="12", iban="NL00X", email="geen-email")
    assert r.status == "created"
    c = r.contact
    assert (c.btw_number, c.kvk, c.iban, c.email) == (None, None, None, None)
    assert "Het btw-nummer 'NL12' op de factuur is ongeldig en is genegeerd." in r.warnings
    assert any(w.startswith("Het KvK-nummer '12'") for w in r.warnings)
    assert any(w.startswith("Het IBAN 'NL00X'") for w in r.warnings)
    assert any(w.startswith("Het e-mailadres 'geen-email'") for w in r.warnings)


def test_invalid_never_raises_even_for_junk(session):
    r = run(session, name="x" * 500, postal_code="1" * 40, country="Nederland")
    assert r.status == "created"
    assert len(r.contact.name) == 200
    assert r.contact.country == "NL"
    assert r.contact.postal_code is None


def test_invalid_id_falls_through_to_name(session):
    c = mk(session, name="Jansen")
    r = run(session, name="Jansen", btw_number="NL12")
    assert (r.contact.id, r.matched_on) == (c.id, "name")
    assert len(r.warnings) == 1


# --- enrichment ---
def test_enrich_fills_only_empty(session):
    c = mk(session, name="Jansen", kvk=KVK, city="Utrecht")
    r = run(
        session,
        name="Jansen",
        kvk=KVK,
        btw_number=BTW,
        iban=IBAN,
        address_line="Dorpsstraat 1",
        postal_code="1234 AB",
        city="Amsterdam",
        email="a@b.nl",
        phone="0612345678",
    )
    c = r.contact
    assert c.btw_number == BTW and c.iban == IBAN
    assert c.address_line == "Dorpsstraat 1" and c.postal_code == "1234 AB"
    assert c.email == "a@b.nl" and c.phone == "0612345678"
    assert c.city == "Utrecht"  # untouched


def test_enrich_never_overwrites_identifiers(session):
    c = mk(session, name="Jansen", btw_number=BTW, iban=IBAN)
    r = run(session, btw_number=BTW, iban=IBAN2, kvk=KVK)
    assert r.contact.iban == IBAN
    assert r.contact.kvk == KVK
    assert r.warnings == ()


def test_enrich_updates_updated_at_only_on_change(session):
    c = mk(session, name="Jansen", kvk=KVK)
    before = c.updated_at
    run(session, kvk=KVK)
    assert c.updated_at == before
    run(session, kvk=KVK, city="Utrecht")
    assert c.updated_at > before


def test_enrich_unique_conflict_skipped_with_warning(session):
    a = mk(session, name="Alfa", kvk=KVK)
    mk(session, name="Beta", iban=IBAN)
    r = run(session, kvk=KVK, iban=IBAN)
    assert r.contact.id == a.id
    assert a.iban is None
    assert r.warnings  # conflict is reported


def test_enrich_on_name_match(session):
    c = mk(session, name="Jansen")
    r = run(session, name="Jansen", kvk=KVK, btw_number=BTW)
    assert r.contact.id == c.id and c.kvk == KVK and c.btw_number == BTW


def test_role_added_on_match(session):
    c = mk(session, name="Jansen", btw_number=BTW)
    assert not c.is_customer
    r = run(session, role="customer", btw_number=BTW)
    assert r.contact.is_customer and r.contact.is_supplier


# --- create ---
def test_create(session):
    r = run(
        session,
        role="customer",
        name=" Nieuwe Klant ",
        kvk="12345678",
        btw_number="nl123456789b01",
        iban="nl91 abna 0417 1643 00",
        address_line="Straat 1",
        postal_code="1000 AA",
        city="Amsterdam",
        country="de",
        email="x@y.nl",
        phone="06",
    )
    c = r.contact
    assert (r.status, r.matched_on) == ("created", None)
    assert c.id is not None and c.is_active
    assert c.is_customer and not c.is_supplier
    assert (c.name, c.kvk, c.btw_number, c.iban) == ("Nieuwe Klant", KVK, BTW, IBAN)
    assert (c.country, c.name_key) == ("DE", "nieuwe klant")
    assert r.warnings == ()


def test_create_default_country(session):
    assert run(session, name="X").contact.country == "NL"


@pytest.mark.parametrize("kw", [{}, {"name": ""}, {"name": "   "}, {"kvk": KVK}])
def test_create_needs_name(session, kw):
    r = run(session, **kw)
    assert r.status == "not_found" and r.contact is None
    assert "Er is geen naam of bedrijfsgegeven gevonden om een relatie op aan te maken." in r.warnings
    assert count(session) == 0


def test_create_false(session):
    r = run(session, name="Nieuw", create=False)
    assert r.status == "not_found" and r.contact is None
    assert count(session) == 0


def test_create_false_still_matches(session):
    c = mk(session, name="Jansen")
    r = run(session, name="Jansen", create=False)
    assert r.status == "matched" and r.contact.id == c.id


# --- idempotency, transaction ---
@pytest.mark.parametrize(
    "kw",
    [
        {"name": "Idem Bedrijf"},
        {"name": "Idem", "kvk": KVK},
        {"name": "Idem", "iban": IBAN, "btw_number": BTW},
        {"kvk": KVK, "name": "Café X & Co B.V."},
    ],
)
def test_idempotent(session, kw):
    first = run(session, **kw)
    second = run(session, **kw)
    assert (first.status, second.status) == ("created", "matched")
    assert first.contact.id == second.contact.id
    assert count(session) == 1


def test_no_commit(session):
    run(session, name="Tijdelijk")
    assert count(session) == 1
    session.rollback()
    assert count(session) == 0
