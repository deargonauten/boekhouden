import re

import pytest

from app.domain.glossary import GLOSSARY, Term, all_terms, get_term

REQUIRED = """grootboek grootrekening dagboek memoriaal verkoopdagboek inkoopdagboek bankdagboek
kasdagboek boeking boekstuk debet credit storno boekjaar periode vergrendelen afsluiten btw
btw_code rgs activa passiva eigen_vermogen opbrengsten kosten systeemrekening debiteuren
crediteuren balans_evenwicht referentie inbox relaties rapportages bank kas
kvk btw_nummer iban klant leverancier archiveren
status_nieuw status_herkend status_geboekt bewaarplicht vingerafdruk""".split()

GUARDED = {"debet", "credit", "grootrekening", "dagboek", "storno", "periode"}


def test_required_keys_present():
    assert set(REQUIRED) <= set(GLOSSARY)


@pytest.mark.parametrize("t", all_terms(), ids=lambda t: t.key)
def test_entry_valid(t: Term):
    assert re.fullmatch(r"[a-z_]+", t.key)
    assert GLOSSARY[t.key] is t
    assert t.term.strip() and t.plain.strip() and t.explanation.strip()
    assert len(t.explanation) <= 220
    assert t.plain.lower() != t.term.lower()
    for rx in t.patterns():
        re.compile(rx, re.I)


def test_keys_unique():
    assert len({t.key for t in all_terms()}) == len(all_terms())


def test_get_term_unknown_raises():
    with pytest.raises(KeyError, match="nope"):
        get_term("nope")


def test_get_term_known():
    assert get_term("debet").term == "Debet"


def test_default_detect_matches_term_word():
    (rx,) = get_term("grootboek").patterns()
    assert re.search(rx, "Het Grootboek", re.I)
    assert not re.search(rx, "Grootboekrekening", re.I)


@pytest.mark.parametrize("t", all_terms(), ids=lambda t: t.key)
def test_explanation_avoids_other_jargon(t: Term):
    for key in GUARDED - {t.key}:
        if {t.key, key} == {"debet", "credit"}:
            continue
        word = get_term(key).term
        assert not re.search(rf"\b{re.escape(word)}\b", t.explanation, re.I), (
            f"{t.key} explanation uses {word!r}; reword in everyday words"
        )


def test_btw_pattern_leaves_btw_nummer_to_its_own_term():
    (rx,) = get_term("btw").patterns()
    assert re.search(rx, "Btw", re.I)
    assert not re.search(rx, "Btw-nummer", re.I)
    assert not re.search(rx, "Btw-code", re.I)
    (rx2,) = get_term("btw_nummer").patterns()
    assert re.search(rx2, "Btw-nummer", re.I)


def test_relation_term_patterns():
    assert re.search(get_term("kvk").patterns()[0], "KvK-nummer", re.I)
    assert re.search(get_term("kvk").patterns()[0], "KvK", re.I)
    assert re.search(get_term("iban").patterns()[0], "IBAN", re.I)
