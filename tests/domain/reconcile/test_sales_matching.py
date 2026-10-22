"""Suggestions for klant payments (pure): number formats, IBAN, multi-invoice, refunds, labels."""

from datetime import date

from app.domain.reconcile.matching import suggest
from app.domain.reconcile.types import OpenItem, TxnView

IBAN = "NL91ABNA0417164300"


def txn(amount, desc="", name="Klant BV", iban=IBAN):
    return TxnView(1, date(2026, 4, 1), amount, name, iban, desc)


def sale(sid, number, open_cents, contact=1, name="Klant BV", iban=IBAN, credit=False, source="sales_invoice"):
    return OpenItem(
        source, sid, contact, name, iban, number, date(2026, 3, 1), date(2026, 3, 31), open_cents,
        is_credit=credit, side="debiteur",
    )


def buy(sid, number, open_cents, contact=9, credit=False):
    return OpenItem("purchase_invoice", sid, contact, "Bol B.V.", "NL00BOL", number, date(2026, 3, 1), None, open_cents, is_credit=credit)


def test_number_with_dash_and_without_both_match():
    items = [sale(1, "2026-0007", 12100), sale(2, "2026-0008", 12100)]
    for desc in ("Betaling factuur 2026-0007", "Betaling factuur 20260007", "Fact 2026 0007 bedankt"):
        found = suggest(txn(12100, desc), items, [])
        assert found[0].confidence == "zeker"
        assert [a.source_id for a in found[0].allocations] == [1]


def test_label_is_plain_dutch_with_kind_and_customer():
    found = suggest(txn(12100, "2026-0007"), [sale(1, "2026-0007", 12100)], [])
    assert found[0].label == "Verkoopfactuur 2026-0007 - Klant BV"
    assert "Het IBAN van de klant klopt" in found[0].reasons
    assert "Het bedrag klopt precies" in found[0].reasons


def test_iban_and_amount_alone_is_zeker_when_unique():
    found = suggest(txn(12100, "bedankt"), [sale(1, "2026-0007", 12100), sale(2, "2026-0008", 5000)], [])
    assert found[0].confidence == "zeker" and found[0].allocations[0].source_id == 1


def test_two_equal_candidates_is_only_waarschijnlijk():
    found = suggest(txn(12100, "bedankt"), [sale(1, "2026-0007", 12100), sale(2, "2026-0008", 12100)], [])
    assert {s.confidence for s in found} == {"waarschijnlijk"}


def test_multi_invoice_suggestion_when_description_names_both():
    items = [sale(1, "2026-0001", 10000), sale(2, "2026-0002", 20000), sale(3, "2026-0003", 5000)]
    found = suggest(txn(30000, "Facturen 2026-0001 en 2026-0002"), items, [])
    best = found[0]
    assert best.confidence == "zeker"
    assert sorted(a.source_id for a in best.allocations) == [1, 2]
    assert best.label == "Verkoopfacturen 2026-0001, 2026-0002 - Klant BV"


def test_partial_payment_is_waarschijnlijk_with_explanation():
    found = suggest(txn(5000, "2026-0007"), [sale(1, "2026-0007", 12100)], [])
    assert found[0].confidence == "waarschijnlijk"
    assert found[0].allocations[0].amount_cents == 5000
    assert any("deel" in r for r in found[0].reasons)


def test_incoming_does_not_suggest_sales_credit_notes_or_purchase_invoices():
    items = [sale(1, "2026-0009", 5000, credit=True), buy(5, "F-1", 5000)]
    assert suggest(txn(5000, "2026-0009 F-1"), items, []) == []


def test_outgoing_refund_matches_sales_credit_note_only():
    items = [sale(1, "2026-0009", 5000, credit=True), sale(2, "2026-0007", 5000), buy(5, "F-1", 5000)]
    found = suggest(txn(-5000, "Terugbetaling 2026-0009"), items, [])
    sales_ids = [a.source_id for s in found for a in s.allocations if a.source == "sales_invoice"]
    assert sales_ids == [1]  # the plain sales invoice is never offered for an outgoing payment
    assert found[0].label == "Verkoopcreditnota 2026-0009 - Klant BV"


def test_opening_item_of_klant_is_suggested():
    item = sale(4, "OUD-1", 4500, source="opening_item")
    found = suggest(txn(4500, "OUD-1"), [item], [])
    assert found[0].confidence == "zeker"
    assert found[0].label == "Openstaande post OUD-1 - Klant BV"


def test_same_contact_on_both_sides_is_not_combined():
    items = [sale(1, "2026-0001", 10000, contact=3), buy(2, "2026-0001", 10000, contact=3, credit=True)]
    found = suggest(txn(20000, "2026-0001"), items, [])
    assert found == []


def test_crediteur_label_unchanged():
    found = suggest(txn(-12100, "F-1", iban="NL00BOL", name="Bol B.V."), [buy(5, "F-1", 12100)], [])
    assert found[0].label == "Bol B.V. - F-1"
