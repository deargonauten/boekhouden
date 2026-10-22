"""Pure suggestion logic: signals, confidence matrix, normalisation, multi-invoice, rules."""

from datetime import date

from app.domain.reconcile.matching import normalize_text, suggest
from app.domain.reconcile.types import OpenItem, RuleView, TxnView

IBAN = "NL91ABNA0417164300"


def txn(amount=-12100, desc="Betaling", name="Bol B.V.", iban=IBAN, id_=1):
    return TxnView(
        id=id_, booking_date=date(2025, 4, 1), amount_cents=amount,
        counterparty_name=name, counterparty_iban=iban, description=desc,
    )


def item(sid=1, number="F-2026/001", open_cents=12100, contact=1, name="Bol B.V.", iban=IBAN,
         is_credit=False, source="purchase_invoice"):
    return OpenItem(
        source=source, source_id=sid, contact_id=contact, contact_name=name, iban=iban,
        number=number, date=date(2025, 3, 1), due_date=None, open_cents=open_cents,
        is_credit=is_credit,
    )


def rule(id_=1, iban=None, needle=None, direction="af", use_count=0):
    return RuleView(id=id_, name=f"regel {id_}", counterparty_iban=iban, description_contains=needle,
                    direction=direction, account_id=10, vat_code="NL_21", contact_id=None,
                    use_count=use_count)


def test_normalize_text():
    assert normalize_text("F-2026/001") == "f2026001"
    assert normalize_text("  Café  Ünïcode ") == "cafeunicode"
    assert normalize_text(None) == ""


def test_number_normalisation_matches_description():
    s = suggest(txn(desc="Betaling factuur F2026001"), [item()], [])
    assert len(s) == 1 and s[0].confidence == "zeker"
    assert s[0].allocations[0].amount_cents == 12100


def test_zeker_exact_amount_and_iban_only():
    s = suggest(txn(desc="overschrijving"), [item()], [])
    assert s[0].confidence == "zeker"


def test_exact_amount_without_iban_or_number_is_waarschijnlijk():
    s = suggest(txn(iban=None, name="Onbekend", desc="x"), [item(iban=None, name="Bol B.V.")], [])
    assert [x.confidence for x in s] == ["waarschijnlijk"]  # amount alone is a signal


def test_name_match_is_a_signal_but_not_zeker():
    s = suggest(txn(iban=None, desc="x", amount=-5000), [item(iban=None, open_cents=12100)], [])
    assert len(s) == 1 and s[0].confidence == "waarschijnlijk"
    assert s[0].allocations[0].amount_cents == 5000  # partial payment covers the full transaction


def test_two_exact_candidates_are_both_waarschijnlijk():
    items = [item(1, "A-100", 12100), item(2, "B-200", 12100)]
    s = suggest(txn(desc="betaling"), items, [])
    assert len(s) == 2 and {x.confidence for x in s} == {"waarschijnlijk"}


def test_number_in_description_disambiguates_exact_candidates():
    items = [item(1, "A-100", 12100), item(2, "B-200", 12100)]
    s = suggest(txn(desc="factuur B200"), items, [])
    assert s[0].confidence == "zeker" and s[0].allocations[0].source_id == 2
    assert all(x.confidence != "zeker" for x in s[1:])


def test_short_invoice_numbers_are_ignored():
    s = suggest(txn(desc="betaling 12", iban=None, name="x", amount=-999), [item(number="12", iban=None, name="Y", open_cents=5000)], [])
    assert s == []


def test_item_smaller_than_transaction_is_not_offered_alone():
    s = suggest(txn(amount=-20000, desc="F2026001"), [item(open_cents=12100)], [])
    assert s == []


def test_direction_af_ignores_credit_notes_bij_ignores_invoices():
    credit = item(5, "C-1", 12100, is_credit=True)
    assert suggest(txn(amount=-12100), [credit], []) == []
    assert suggest(txn(amount=12100), [item()], []) == []
    s = suggest(txn(amount=12100, desc="Creditnota C1"), [credit], [])
    assert s and s[0].confidence == "zeker"


def test_multi_invoice_sum_named_in_description():
    items = [item(1, "F-001", 5000), item(2, "F-002", 7100), item(3, "F-003", 9999)]
    s = suggest(txn(amount=-12100, desc="Facturen F001 en F002"), items, [])
    best = s[0]
    assert best.confidence == "zeker"
    assert {a.source_id for a in best.allocations} == {1, 2}
    assert sum(a.amount_cents for a in best.allocations) == 12100


def test_multi_invoice_needs_same_contact():
    items = [item(1, "F-001", 5000, contact=1), item(2, "F-002", 7100, contact=2, name="Anders", iban="NL20INGB0001234567")]
    s = suggest(txn(amount=-12100, desc="F001 F002"), items, [])
    assert all(len(x.allocations) == 1 for x in s) or s == []
    assert not any(len(x.allocations) == 2 for x in s)


def test_multi_invoice_limited_to_six_candidates():
    items = [item(i, f"F-{i:03d}", 1000 + i) for i in range(1, 8)]
    desc = " ".join(f"F{i:03d}" for i in range(1, 8))
    total = sum(i.open_cents for i in items[:2])
    s = suggest(txn(amount=-total, desc=desc), items, [])
    assert not any(len(x.allocations) > 1 for x in s)


def test_multi_invoice_amount_must_match():
    items = [item(1, "F-001", 5000), item(2, "F-002", 7100)]
    s = suggest(txn(amount=-12000, desc="F001 F002"), items, [])
    assert not any(len(x.allocations) == 2 for x in s)


def test_rule_suggestion_iban_and_needle_is_zeker():
    r = rule(1, iban=IBAN, needle="abonnement")
    s = suggest(txn(desc="Abonnement mei", amount=-1500), [], [r])
    assert len(s) == 1 and s[0].kind == "rule" and s[0].confidence == "zeker"
    assert s[0].rule_id == 1 and s[0].direct_lines[0].amount_cents == 1500
    assert s[0].direct_lines[0].account_id == 10 and s[0].direct_lines[0].vat_code == "NL_21"


def test_rule_single_condition_is_waarschijnlijk():
    s = suggest(txn(desc="x"), [], [rule(1, iban=IBAN)])
    assert s[0].confidence == "waarschijnlijk"
    s = suggest(txn(desc="Kosten pakket", iban="NL20INGB0001234567"), [], [rule(1, needle="kosten")])
    assert s[0].confidence == "waarschijnlijk"


def test_rule_direction_respected():
    assert suggest(txn(amount=1500), [], [rule(1, iban=IBAN, direction="af")]) == []
    assert suggest(txn(amount=1500), [], [rule(1, iban=IBAN, direction="beide")])


def test_rules_ordered_by_specificity_then_use_count():
    rules = [
        rule(1, needle="kosten", use_count=50),
        rule(2, iban=IBAN, use_count=1),
        rule(3, iban=IBAN, needle="kosten", use_count=0),
        rule(4, iban=IBAN, use_count=9),
    ]
    out = suggest(txn(desc="Kosten", amount=-100), [], rules)
    assert [s.rule_id for s in out] == [3, 4, 2, 1]


def test_zeker_match_ranks_above_waarschijnlijk_rule():
    out = suggest(txn(desc="F2026001"), [item()], [rule(1, iban=IBAN)])
    assert out[0].kind == "match" and out[0].confidence == "zeker"
    assert out[1].kind == "rule"


def test_suggest_is_deterministic():
    items = [item(1, "A-100", 12100), item(2, "B-200", 12100)]
    assert suggest(txn(), items, []) == suggest(txn(), list(reversed(items)), [])


def test_suggestion_keys_are_unique_and_stable():
    items = [item(1, "A-100", 12100), item(2, "B-200", 12100)]
    keys = [s.key for s in suggest(txn(), items, [])]
    assert len(set(keys)) == 2 and keys[0].startswith("match:")
