VERDICT: APPROVE

## Reasoning
- Process: spec approved; round 1 built in parts A+B (data, matching, rules, booking service) and C (web, templates, glossary); round 1 reviews gave code REWORK (2 findings), ux-ui REWORK (1 blocking, 2 nice-to-have), security PASS. Round 2 fixed all three blocking items and added regression tests. Round 2 reviews: code PASS, ux-ui PASS. Review rounds stayed within the max of 2.
- Round-1 blocking findings are resolved in the code: the generic storno of a bank booking is now refused with a link to "Ongedaan maken" (409, plain Dutch), undo refuses a locked original period even when today's period is open, and the creditnota explainer is in place (info("creditnota") plus hint).
- Spot-checked the copy and rules against the spec: the confirm text for Negeren, "Deze mutatie is al verwerkt.", the over-allocation message, "Kies een rekening voor deze regel.", the unsupported-VAT refusal (verlegd/EU/export), the Zeker/Waarschijnlijk labels, the Akkoord button, "N te verwerken" on /bank, and the summary "Verdeeld X van Y, nog Z te verdelen" are all present. The glossary terms afletteren, deelbetaling, direct_boeken and matchingregel are in app/domain/glossary.py. bank_match has update and delete triggers in migration 0011 (only reversed_at may be set, no delete).
- Test result (given by the orchestrator, not rerun): full suite 1968 passed.
- Spec deviations that are reasoned and accepted: the manual match page shows the invoice list and the direct-booking lines in one form instead of two tabs (C's stated reason: allows mixed booking in one submit, as AC 8 requires). Both sections are present; the tab names "Past bij factuur" and "Direct boeken" do not appear as labels in the UI.

## Acceptance criteria check
1. Screen /bank/afletteren with filters, newest first, pagination, suggestion, confidence label, Akkoord; "N te verwerken" on /bank. MET (count is on the bank index and the tab, not the nav sidebar; the spec says "Nav/bank index", so this is met).
2. Pure deterministic suggest with IBAN, amount, invoice number, name signals; Zeker/Waarschijnlijk rule; direction; multi-invoice subset-sum for up to 6 candidates. MET (builder's documented interpretation of the Zeker rule is consistent with the spec).
3. Akkoord books atomically; bank_match, paid_cents, status geboekt, journal_entry_id; full-cover only. MET.
4. Manual match page with invoice list, prefilled amounts capped at remainder, live summary, booking blocked until remainder is 0. MET in substance; tab structure deviates (one form), see above.
5. Partial payment allowed; over-allocation refused with the spec message. MET.
6. Split and mixed creditnota net, one 3000 line per allocation. MET (builder tests and service).
7. Opening items matchable via paid_cents. MET (service tests).
8. Direct-book lines with btw defaults from rule, last IBAN booking, or Account.default_vat_code; unsupported btw refused; combination with invoice allocations. MET.
9. "Onthoud dit voor volgende keer" creates rules; rules only as suggestions; /bank/regels with deactivate/reactivate; no delete. MET.
10. Negeren with the exact confirm text; Terugzetten; "Genegeerd" filter. MET.
11. Ongedaan maken via reverse_entry, reversed_at, paid_cents recomputed, status back to nieuw; refused when locked or already reversed. MET (locked-original-period gap fixed in round 2).
12. Append-only: bank_match triggers forbid delete and restrict update to reversed_at. MET.
13. Plain Dutch errors, never raw exceptions. MET for every error path checked.
14. Double booking yields one entry; second gets "Deze mutatie is al verwerkt."; guarded UPDATE re-check. MET (double accept test returns 409).
15. /inkoop and crediteuren reflect payments via open_amount/status; invoice-to-transaction link optional. MET for the required part; the optional link is not checked.
Usable without bookkeeping knowledge (CLAUDE.md): plain-Dutch headings ("Welke factuur is dit?", "Wat is dit voor uitgave?", "Nog te verdelen"), info icons on glossary terms, defaults for rekening/btw, and plain-language tests. MET.

## Outstanding issues
- Security was reviewed in round 1 only. Round 2 changed the storno guard in the ledger route and the reconcile undo; the change tightens integrity checks and has regression tests, so I consider the risk low, but it was not re-reviewed.
- Invoice-number matching is a plain substring on normalised text (min 3 chars), so a short number can match inside a longer one. This produces a false "Waarschijnlijk" at most. Nothing is auto-booked, so the user confirms every match.
- Visual verification was not done: both UX reviewers noted that no app was running on localhost:8000, so the screens were judged from templates only.
- Optional AC 15 link from invoice detail to paying transaction is not built (allowed as optional).
- Tab labels differ from spec AC 4 (see deviations).

## What the human should look at
Not blocking, but worth a short look in the browser before relying on it:
- /bank/afletteren and /bank/transacties/{id}/afletteren: layout, and whether the single combined form reads clearly for a non-accountant.
- The creditnota and "Wat is dit voor uitgave?" wording for incoming transactions.
- /bank/regels: whether the rule names and conditions make sense.
- Any bank transaction with an invoice number shorter than about 5 characters, to see that suggestions are reasonable.

STATUS: DONE
