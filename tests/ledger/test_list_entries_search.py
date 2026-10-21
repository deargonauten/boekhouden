"""list_entries(q=...): search on boekstuknummer, omschrijving and referentie."""

from app.domain.ledger import list_entries


def test_q_matches_description_case_insensitive(session, year2025, make_entry):
    make_entry(description="Kantoorspullen Bol")
    make_entry(description="Huur")
    page = list_entries(session, q="kantoor")
    assert [r.description for r in page.items] == ["Kantoorspullen Bol"]
    assert page.total == 1


def test_q_matches_entry_number_and_reference(session, year2025, make_entry):
    a = make_entry(description="Een", reference="FACT-2025-007")
    make_entry(description="Twee")
    assert [r.id for r in list_entries(session, q="fact-2025").items] == [a.id]
    assert [r.id for r in list_entries(session, q=a.entry_number.lower()).items] == [a.id]


def test_q_percent_and_underscore_are_literal(session, year2025, make_entry):
    pct = make_entry(description="Korting 10% extra")
    und = make_entry(description="a_b")
    make_entry(description="Korting 10 procent")
    make_entry(description="axb")
    assert [r.id for r in list_entries(session, q="10%").items] == [pct.id]
    assert [r.id for r in list_entries(session, q="a_b").items] == [und.id]


def test_blank_q_is_ignored_and_combines_with_journal_and_paging(session, year2025, make_entry):
    for _ in range(3):
        make_entry(journal="VK", description="Verkoop test")
    make_entry(journal="MEM", description="Verkoop test")
    assert list_entries(session, q="  ").total == 4
    assert list_entries(session, q="verkoop", journal_code="VK").total == 3
    small = list_entries(session, q="verkoop", journal_code="VK", page=2, per_page=2)
    assert small.total == 3 and len(small.items) == 1


def test_page_beyond_last_shows_last_page(session, year2025, make_entry):
    for _ in range(3):
        make_entry()
    page = list_entries(session, page=99, per_page=2)
    assert page.page == 2 and len(page.items) == 1
