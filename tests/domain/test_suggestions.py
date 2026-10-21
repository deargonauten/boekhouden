from datetime import date

import pytest
from sqlalchemy import delete, select

from app.domain.ledger import (
    ACCOUNT_TYPE_LABELS,
    JOURNAL_TYPE_LABELS,
    add_account,
    create_fiscal_year,
    default_journal_id,
    suggest_account_code,
    suggest_fiscal_year,
)
from app.models import Account, Journal


def test_type_labels_are_plain_dutch():
    assert set(ACCOUNT_TYPE_LABELS) == {"asset", "liability", "equity", "revenue", "expense"}
    assert ACCOUNT_TYPE_LABELS["asset"] == "Wat je bezit (Activa)"
    assert ACCOUNT_TYPE_LABELS["liability"] == "Wat je schuldig bent (Passiva)"
    assert ACCOUNT_TYPE_LABELS["equity"] == "Eigen vermogen"
    assert ACCOUNT_TYPE_LABELS["revenue"] == "Opbrengsten (wat je verdient)"
    assert ACCOUNT_TYPE_LABELS["expense"] == "Kosten (wat je uitgeeft)"
    assert JOURNAL_TYPE_LABELS == {
        "verkoop": "Verkoop (verkoopfacturen)",
        "inkoop": "Inkoop (inkoopfacturen)",
        "bank": "Bank (bankrekening)",
        "kas": "Kas (contant geld)",
        "memoriaal": "Memoriaal (overige boekingen)",
    }


def _all_codes(session):
    return set(session.scalars(select(Account.code)))


def _type_codes(session, type_):
    return [int(c) for c in session.scalars(select(Account.code).where(Account.type == type_))]


@pytest.mark.parametrize("type_", ["asset", "liability", "equity", "revenue", "expense"])
def test_suggest_account_code_is_free_four_digits(session, type_):
    code = suggest_account_code(session, type_)
    assert len(code) == 4 and code.isdigit()
    assert code not in _all_codes(session)


def test_suggest_account_code_is_highest_plus_ten_rounded(session):
    top = max(_type_codes(session, "expense"))
    assert suggest_account_code(session, "expense") == f"{(top + 10) // 10 * 10:04d}"


def test_suggest_account_code_is_deterministic(session):
    assert suggest_account_code(session, "expense") == suggest_account_code(session, "expense")


def test_suggest_account_code_moves_on_after_use(session):
    first = suggest_account_code(session, "expense")
    add_account(session, code=first, name="Test", type="expense")
    second = suggest_account_code(session, "expense")
    assert second != first
    assert second not in _all_codes(session)


def test_suggest_account_code_collision_falls_back_above_minimum(session):
    top = max(_type_codes(session, "expense"))
    slot = f"{(top + 10) // 10 * 10:04d}"
    add_account(session, code=slot, name="Bezet door ander type", type="asset")
    code = suggest_account_code(session, "expense")
    assert code != slot
    assert code not in _all_codes(session)
    assert int(code) > min(_type_codes(session, "expense"))


def test_suggest_account_code_range_full_above_minimum(session):
    lo = min(_type_codes(session, "expense"))
    for n in range(lo, 10000):
        if f"{n:04d}" not in _all_codes(session):
            add_account(session, code=f"{n:04d}", name=f"Vul {n}", type="asset")
    code = suggest_account_code(session, "expense")
    assert len(code) == 4 and code.isdigit()
    assert code not in _all_codes(session)


def test_suggest_account_code_type_without_accounts(session):
    session.execute(delete(Account).where(Account.type == "equity"))
    code = suggest_account_code(session, "equity")
    assert len(code) == 4 and code not in _all_codes(session)


def test_suggest_fiscal_year_no_years(session):
    assert suggest_fiscal_year(session, date(2026, 5, 1)) == 2026


def test_suggest_fiscal_year_current_exists(session):
    create_fiscal_year(session, 2026)
    assert suggest_fiscal_year(session, date(2026, 5, 1)) == 2027


def test_suggest_fiscal_year_consecutive_years(session):
    for y in (2026, 2027, 2028):
        create_fiscal_year(session, y)
    assert suggest_fiscal_year(session, date(2026, 5, 1)) == 2029


def test_suggest_fiscal_year_ignores_past_years_and_gaps(session):
    create_fiscal_year(session, 2025)
    create_fiscal_year(session, 2027)
    assert suggest_fiscal_year(session, date(2026, 5, 1)) == 2026


def test_default_journal_id_memoriaal(session):
    jid = default_journal_id(session, "memoriaal")
    assert jid == session.scalar(select(Journal.id).where(Journal.code == "MEM"))


def test_default_journal_id_skips_inactive_and_returns_none(session):
    for j in session.scalars(select(Journal).where(Journal.type == "memoriaal")):
        j.is_active = False
    session.flush()
    assert default_journal_id(session, "memoriaal") is None
