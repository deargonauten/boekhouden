VERDICT: REWORK

## Summary
The import flow is well structured and the reported suite passes (1659 passed, 1 deselected). One parser bug persists reversal transactions with the wrong sign; the existing golden test reinforces that error.

## Blocking findings
- [high] app/domain/bank/parsers/camt053.py:84: `RvslInd=true` flips the sign derived from `CdtDbtInd`. In CAMT, the indicator already describes the current entry: a reversal marked `DBIT` decreases the balance. The supplied fixture reproduces the bug: its €20 debit reversal becomes `+2000` cents. This stores incorrect immutable amounts and can select the wrong counterparty. The [ISO CAMT.053 definition](https://www.iso20022.org/message/mdr/12666/download/111) confirms that reversal identifies the original operation, rather than changing the current indicator’s meaning. → Derive the sign solely from `CdtDbtInd`; correct the fixture’s balance and golden expectation, and cover both credit and debit reversals with targeted tests.

## Nice-to-have
None.

STATUS: DONE