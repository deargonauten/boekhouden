"""Rule matching (pure) and the small rules service."""

from datetime import date

import pytest

from app.domain.reconcile import ReconcileError, create_rule, list_rules, rule_matches, set_rule_active
from app.domain.reconcile.rules import rule_specificity, sort_rules
from app.domain.reconcile.types import RuleView, TxnView

IBAN = "NL20INGB0001234567"


def txn(amount=-100, desc="Abonnement mei", iban=IBAN):
    return TxnView(1, date(2025, 4, 1), amount, "Telecom", iban, desc)


def rule(iban=None, needle=None, direction="af", id_=1, use_count=0):
    return RuleView(id_, "r", iban, needle, direction, 1, None, None, use_count)


def test_rule_matching_conditions():
    assert rule_matches(rule(iban=IBAN), txn())
    assert rule_matches(rule(iban="nl20 ingb 0001 2345 67"), txn())
    assert not rule_matches(rule(iban="NL91ABNA0417164300"), txn())
    assert rule_matches(rule(needle="ABONNEMENT"), txn())
    assert rule_matches(rule(needle="abon-nement"), txn())
    assert not rule_matches(rule(needle="telefoon"), txn())


def test_both_conditions_must_hold():
    assert rule_matches(rule(iban=IBAN, needle="abonnement"), txn())
    assert not rule_matches(rule(iban=IBAN, needle="telefoon"), txn())
    assert not rule_matches(rule(iban="NL91ABNA0417164300", needle="abonnement"), txn())


def test_rule_without_conditions_never_matches():
    assert not rule_matches(rule(), txn())


def test_direction():
    assert not rule_matches(rule(iban=IBAN, direction="bij"), txn(-100))
    assert rule_matches(rule(iban=IBAN, direction="bij"), txn(100))
    assert rule_matches(rule(iban=IBAN, direction="beide"), txn(100))


def test_specificity_and_order():
    assert rule_specificity(rule(iban=IBAN, needle="x")) == 3
    assert rule_specificity(rule(iban=IBAN)) == 2
    assert rule_specificity(rule(needle="x")) == 1
    rules = [rule(needle="abc", id_=1, use_count=9), rule(iban=IBAN, id_=2), rule(iban=IBAN, id_=3, use_count=2)]
    assert [r.id for r in sort_rules(rules)] == [3, 2, 1]


def test_create_rule_validation(session, acc):
    base = dict(name="Telecom", direction="af", account_id=acc("4625"))
    with pytest.raises(ReconcileError):
        create_rule(session, counterparty_iban=None, description_contains=None, **base)
    with pytest.raises(ReconcileError) as exc:
        create_rule(session, counterparty_iban=None, description_contains="ab", **base)
    assert "te kort" in exc.value.message
    with pytest.raises(ReconcileError):
        create_rule(session, counterparty_iban=IBAN, description_contains=None, **{**base, "direction": "fout"})
    with pytest.raises(ReconcileError):
        create_rule(session, counterparty_iban=IBAN, description_contains=None, **{**base, "account_id": 99999})


def test_create_toggle_and_list(session, acc):
    r = create_rule(session, name="Telecom", counterparty_iban="nl20 ingb 0001 2345 67", description_contains=None,
                    direction="af", account_id=acc("4625"), vat_code="NL_21")
    session.commit()
    rows = list_rules(session)
    assert rows[0].counterparty_iban == IBAN and rows[0].is_active and rows[0].use_count == 0
    assert rows[0].account_code == "4625" and "IBAN" in rows[0].condition_text
    set_rule_active(session, r.id, False)
    session.commit()
    assert not list_rules(session)[0].is_active
    assert list_rules(session, include_inactive=False) == []
    set_rule_active(session, r.id, True)
    with pytest.raises(ReconcileError):
        set_rule_active(session, 999, True)
