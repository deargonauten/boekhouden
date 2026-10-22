from pathlib import Path

import pytest

from app.domain.bank.parsers import parse_statement

FIXTURES = Path(__file__).parent / "fixtures"


def _camt_with_entry(indicator: str, reversal: bool, closing: str) -> bytes:
    xml = (FIXTURES / "camt053_002.xml").read_text()
    start = xml.index("<Ntry>")
    end = xml.rindex("</Stmt>")
    entry = (
        f'<Ntry><Amt Ccy="EUR">20.00</Amt><CdtDbtInd>{indicator}</CdtDbtInd>'
        f'{"<RvslInd>true</RvslInd>" if reversal else ""}<Sts>BOOK</Sts>'
        "<BookgDt><Dt>2024-03-04</Dt></BookgDt><AcctSvcrRef>R9</AcctSvcrRef>"
        "<AddtlNtryInf>Terugboeking</AddtlNtryInf></Ntry>"
    )
    return (xml[:start] + entry + xml[end:]).replace("2150.90", closing).encode()


@pytest.mark.parametrize(
    ("indicator", "reversal", "expected", "closing"),
    [
        ("CRDT", True, 2000, "1020.00"),  # reversed debit: balance goes up
        ("DBIT", True, -2000, "980.00"),  # reversal of a credit: balance goes down
        ("CRDT", False, 2000, "1020.00"),
        ("DBIT", False, -2000, "980.00"),
    ],
)
def test_camt053_sign_comes_from_cdtdbtind_only(indicator, reversal, expected, closing):
    st = parse_statement(_camt_with_entry(indicator, reversal, closing))
    assert [t.amount_cents for t in st.transactions] == [expected]
    assert st.balance_difference_cents == 0
