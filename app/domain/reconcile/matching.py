"""Suggestions for a bank transaction (pure, deterministic, no database).

Signals: IBAN equal, exact amount, invoice number in the description, contact name equal.
"Zeker" = exactly one candidate set pays the amount exactly AND (invoice number in the
description OR IBAN match). Anything else with at least one signal is "waarschijnlijk".
"""

from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations

from app.domain.bank.iban import normalize_iban
from app.domain.money import format_euro
from app.domain.reconcile.rules import normalize_text, rule_matches, rule_specificity
from app.domain.reconcile.types import (
    CONFIDENCE_WAARSCHIJNLIJK,
    CONFIDENCE_ZEKER,
    KIND_MATCH,
    KIND_RULE,
    Allocation,
    DirectLine,
    OpenItem,
    RuleView,
    Suggestion,
    TxnView,
)
from app.domain.relations.validation import normalize_name

NUMBER_MIN_LENGTH = 3
MAX_MULTI_CANDIDATES = 6

__all__ = ["normalize_text", "suggest"]


def _signals(txn: TxnView, item: OpenItem, desc_key: str, iban: str, name_key: str) -> list[str]:
    found = []
    number_key = normalize_text(item.number)
    if len(number_key) >= NUMBER_MIN_LENGTH and number_key in desc_key:
        found.append("number")
    if iban and normalize_iban(item.iban) == iban:
        found.append("iban")
    if name_key and normalize_name(item.contact_name) == name_key:
        found.append("name")
    return found


_REASONS = {
    "number": "Het factuurnummer staat in de omschrijving",
    "iban": "Het IBAN van de leverancier klopt",
    "name": "De naam van de leverancier komt overeen",
}
_WEIGHT = {"number": 4, "iban": 3, "name": 2, "amount": 1}


def _label(items: Sequence[OpenItem]) -> str:
    return f"{items[0].contact_name} - " + ", ".join(i.number for i in items)


def _match_suggestions(txn: TxnView, items: Sequence[OpenItem]) -> list[tuple[tuple, Suggestion]]:
    want_credit = txn.direction == "bij"
    eligible = [i for i in items if i.is_credit == want_credit and i.open_cents > 0]
    desc_key = normalize_text(txn.description)
    iban = normalize_iban(txn.counterparty_iban)
    name_key = normalize_name(txn.counterparty_name)
    amount = txn.abs_cents

    # candidate: (items, allocations, signals, exact)
    candidates: list[tuple[tuple[OpenItem, ...], tuple[Allocation, ...], list[str], bool]] = []
    signals_of = {i.ref: _signals(txn, i, desc_key, iban, name_key) for i in eligible}

    for item in eligible:
        if item.open_cents < amount:
            continue  # one item must cover the whole transaction on its own
        signals = list(signals_of[item.ref])
        exact = item.open_cents == amount
        if exact:
            signals.append("amount")
        if signals:
            candidates.append(((item,), (Allocation(item.source, item.source_id, amount),), signals, exact))

    by_contact: dict[int, list[OpenItem]] = defaultdict(list)
    for item in eligible:
        if "number" in signals_of[item.ref]:
            by_contact[item.contact_id].append(item)
    for named in by_contact.values():
        if not 2 <= len(named) <= MAX_MULTI_CANDIDATES:
            continue
        named = sorted(named, key=lambda i: (i.date, i.source, i.source_id))
        for size in range(2, len(named) + 1):
            for combo in combinations(named, size):
                if sum(i.open_cents for i in combo) != amount:
                    continue
                signals = ["number"]
                if all("iban" in signals_of[i.ref] for i in combo):
                    signals.append("iban")
                if all("name" in signals_of[i.ref] for i in combo):
                    signals.append("name")
                signals.append("amount")
                allocs = tuple(Allocation(i.source, i.source_id, i.open_cents) for i in combo)
                candidates.append((combo, allocs, signals, True))

    # An invoice number in the description singles out its candidate; otherwise the exact
    # candidate must be the only one.
    exact_all = sum(1 for c in candidates if c[3])
    exact_named = sum(1 for c in candidates if c[3] and "number" in c[2])
    out = []
    for combo, allocs, signals, exact in candidates:
        if not exact:
            unique = False
        elif "number" in signals:
            unique = exact_named == 1
        else:
            unique = "iban" in signals and exact_named == 0 and exact_all == 1
        confidence = CONFIDENCE_ZEKER if unique else CONFIDENCE_WAARSCHIJNLIJK
        reasons = [_REASONS[s] for s in signals if s in _REASONS]
        if "amount" in signals:
            reasons.append("Het bedrag klopt precies")
        elif combo[0].open_cents > amount:
            reasons.append(
                f"Je betaalt een deel: {format_euro(amount)} van {format_euro(combo[0].open_cents)}"
            )
        score = sum(_WEIGHT[s] for s in signals)
        suggestion = Suggestion(
            kind=KIND_MATCH,
            allocations=allocs,
            rule_id=None,
            direct_lines=(),
            confidence=confidence,
            reasons=tuple(reasons),
            contact_id=combo[0].contact_id,
            label=_label(combo),
            score=score,
        )
        out.append(((0 if confidence == CONFIDENCE_ZEKER else 1, -score, 0, suggestion.key), suggestion))
    return out


def _rule_suggestions(txn: TxnView, rules: Sequence[RuleView]) -> list[tuple[tuple, Suggestion]]:
    out = []
    for rule in rules:
        if not rule_matches(rule, txn):
            continue
        specificity = rule_specificity(rule)
        both = specificity == 3
        reasons = ["Je hebt dit eerder zo geboekt"]
        if rule.counterparty_iban:
            reasons.append("Het IBAN komt overeen met een onthouden keuze")
        if rule.description_contains:
            reasons.append(f'De omschrijving bevat "{rule.description_contains}"')
        confidence = CONFIDENCE_ZEKER if both else CONFIDENCE_WAARSCHIJNLIJK
        suggestion = Suggestion(
            kind=KIND_RULE,
            allocations=(),
            rule_id=rule.id,
            direct_lines=(
                DirectLine(rule.account_id, txn.abs_cents, rule.vat_code, txn.description.strip() or None),
            ),
            confidence=confidence,
            reasons=tuple(reasons),
            contact_id=rule.contact_id,
            label=rule.name,
            score=specificity,
        )
        out.append(((0 if both else 1, -specificity, -rule.use_count, suggestion.key), suggestion))
    return out


def suggest(txn: TxnView, items: Sequence[OpenItem], rules: Sequence[RuleView]) -> list[Suggestion]:
    """All suggestions, best first. Only suggestions whose allocation covers the whole
    transaction amount are returned. Same input always gives the same output."""
    ranked = _match_suggestions(txn, items) + _rule_suggestions(txn, rules)
    # zeker first; then (matches before rules at equal strength) by score, usage and key
    ranked.sort(key=lambda pair: (pair[0][0], pair[0][1], pair[0][2], pair[1].kind != KIND_MATCH, pair[0][3]))
    return [s for _, s in ranked]
