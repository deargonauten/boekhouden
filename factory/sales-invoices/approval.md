VERDICT: HUMAN_REVIEW

## Reasoning
The process was followed. Spec was approved, builders A, B and C ran in round 1 and were merged, and the review rounds ran within the limit of two. Round 1 gave security PASS, code REWORK (3 findings) and ux-ui REWORK (1 finding). Fix builders D and E addressed all four in round 2. Round 2 gave code PASS and ux-ui PASS. Security was not re-run in round 2, which I accept because the round-2 changes touch credit-amount arithmetic, PDF rendering flags and a new htmx endpoint, not new access or input surfaces.

The domain core is in place: gapless numbering from a counter table, immutability triggers, VAT rounding per rate group, journal entries for invoices and credit notes, credit applications, ageing, reminders, and bank reconciliation on the debiteur side (migration 0013 with triggers recreated). Grep confirms the plain-Dutch messages from the spec exist in the code, and the glossary has all listed keys. The test result given by the orchestrator is 2222 passed, 1 deselected. I did not rerun the suite.

I am choosing HUMAN_REVIEW for three reasons, none of which is a code defect found in review:
1. The live due-date update (AC 19 and 20) depends on an htmx trigger in `app/web/templates/sales/edit.html`. Only the server endpoint `POST /verkoop/termijn` is covered by tests. The trigger filter uses `.includes(...)` inside a bracket expression. htmx 2.0.4 does parse nested brackets, but I could not confirm that `.includes` evaluates as intended. If it does not, the filter falls back to firing on every change, which is harmless but not what was intended. Nobody has seen the behaviour in a browser; both the code reviewer and the ux-ui reviewer flagged this as unverified.
2. AC 30 asks for a "Past bij factuur" tab on the reconcile screen. Builder C built a klant dropdown plus search on the single "Welke factuur is dit?" card instead. The function is covered, but the layout differs from the spec.
3. Visual judgement of the PDF and the /verkoop screens has not been done by anyone. The PDF layout was never looked at, and the ux-ui review explicitly says visual rendering is unverified.

## Acceptance criteria check (met / not met each)
Numbering and statuses
- AC 1 numbering `YYYY-NNNN`, shared series, counter restart per year: met (migration 0012, `numbering.py`, tests).
- AC 2 counter in finalize transaction, rollback on failure: met (rollback tests reported in build A).
- AC 3 chronological guard with message: met (message present in `errors.py`).
- AC 4 immutability by triggers and service message: met (triggers in 0012, message present).
- AC 5 storno shown as "Gestorneerd", warning text: met (labels and warning text present).

Content and validation
- AC 6 finalize validation with plain messages and links: met (messages present in `validation.py`, "Het totaal is" present).
- AC 7 optional leverdatum, referentie, note: met (fields and labels present). The 500-character limit on the note was not checked by me.
- AC 8 PDF content and totals per rate, payment line, credit note wording: met (`pdf.py` per build B, wording strings present).
- AC 9 snapshot of seller and buyer at finalize: met (snapshot columns in 0012, CHECK requires them when definitief).

Amounts and VAT
- AC 10 line and rate-group rounding in integer arithmetic: met (`amounts.py`, tests for rounding and per-group VAT).
- AC 11 Dutch money format and comma or dot input: met per build reports; not re-checked.

Journal entry
- AC 12 invoice entry: met (`entries.py`, tests). Missing-journal message present.
- AC 13 credit note entry with swapped sides: met (tests reported).
- AC 14 trial balance 1300 and 3100/3110: met (trial balance tests reported).

Credit notes
- AC 15 prefill, quantity-only edit, cumulative quantity and amount cap: met after round 2 (`_cap_credit_totals`, messages present).
- AC 16 credit due date equals invoice date: met (build A).
- AC 17 verrekening via `sales_credit_application`: met.
- AC 18 linked documents and status "Gecrediteerd"/"Betaald": met (detail template shows linked documents).

Payment terms
- AC 19 term stored, default from klant else 30, term 0 "Direct betalen": partly met. The term 0 label appears as lower-case "direct betalen" in the text, not the spec's "Direct betalen". The recalculation on change depends on the unverified htmx trigger (see Reasoning).
- AC 20 pre-filled defaults and explanations, revenue account follows btw-code: met in code. Live refresh is the unverified part.

Debiteuren and overview
- AC 21 /verkoop with stat cards, tabs, filters, pagination and empty state: met (tab_items, stats, "Maak je eerste factuur" present).
- AC 22 per-klant ageing with buckets and totals: met (bucket labels present in `types.py`, "Nog niet vervallen" present).
- AC 23 derived status at read time: met (`derive_status`, labels).
- AC 24 debiteur opening items in overview and ageing: met (build A and C, tests).

Bank reconciliation
- AC 25 sales provider in PROVIDERS, `sales_invoice` source, migration 0013: met (both triggers recreated, migration tests).
- AC 26 direction rules and mixed-sides message: met (message present in `errors.py`).
- AC 27 posting rules bij (1300 credit) and af (1300 debit): met (tests in build C).
- AC 28 suggestion signals reused: met (`matching.py`).
- AC 29 paid_cents recomputed on undo, over-allocation refused: met (tests).
- AC 30 reconcile label "Verkoopfactuur ..." and automatic payment status: met. "Past bij factuur" tab: NOT met as specified. A klant dropdown with search is used instead (deviation, see Outstanding issues).

Reminders
- AC 31 eligibility, messages, levels, append-only rows, no journal entry: met (messages present, levels present).
- AC 32 preview, POST stores and makes PDF, copyable text and mailto: met (mailto present, tests in web).
- AC 33 reminder history and "Herinnering gemaakt" marker: met (label present in list and debtors templates).

PDF
- AC 34 ReportLab dependency, pypdf in dev group: met (reports; uv.lock changed).
- AC 35 pure render functions, A4, invariant=1, euro sign verified: met per build B.
- AC 36 stored PDF, concept preview, rollback message: met (message present; round-2 fix ensures no CONCEPT marker on stored PDFs, with regression test).

Plain language
- Glossary keys for all terms listed in the spec are present in `app/domain/glossary.py`. Plain-language and suite tests are green per the orchestrator's result.

## Outstanding issues
- AC 30: "Past bij factuur" tab not built. The klant dropdown and search on the reconcile card cover the same function. I accept this as a layout deviation, but the owner should know.
- AC 19 and 20: the live due-date update in the editor has never been seen in a browser. Only the endpoint is tested. The htmx filter may not behave exactly as intended, though the failure mode I can see is benign (extra requests, not wrong data).
- Term 0 label is lower case ("direct betalen"). Cosmetic.
- Visual design of the PDF and the /verkoop screens is unreviewed by anyone.
- Security was not re-run after round 2. I see no new surface in the round-2 changes.
- `factory/sales-invoices/reviews/round-2/` is untracked in git. Housekeeping: commit or remove it.

## What the human should look at
1. Open /verkoop/nieuw in the browser. Pick a klant with a set betaaltermijn, then change the factuurdatum and the term. Check that the vervaldatum and the hint update. Tick "Zelf kiezen" and check that a typed date is kept. Check that the confirm screen shows the dates.
2. Download a PDF of a concept and of a finalized invoice. Check the layout, multi-page behaviour and the absence of "CONCEPT" on the finalized one. Check a creditnota too.
3. On the bank reconcile screen, check that the klant dropdown and search find an open sales invoice and that the suggestion label reads "Verkoopfactuur 2026-xxxx - Klant". Decide whether the dropdown is acceptable instead of the "Past bij factuur" tab.
4. Read the /verkoop and debiteuren screens once as a non-accountant for plain-Dutch wording.

STATUS: DONE
