# Round 2 fix

- CAMT.053: sign now solely from CdtDbtInd (RvslInd no longer flips). Fixture camt053_002 reversal entry is now CRDT (reversed debit), balances still reconcile; camt053_008 has no reversal. New tests/bank/parsers/test_camt_reversal.py covers credit- and debit-reversal. Dependent counts/amounts unchanged.
- MT940 RC/RD checked: RC (reversal of credit) = minus, RD = plus; correct, unchanged.
- Spec section on parsers/list columns updated.
- Transactions table header: "Saldo erna" + info icon; glossary term saldo_na_mutatie.
- account_form name hint no longer promises an automatic name when editing.
- Full suite: 1665 passed.
