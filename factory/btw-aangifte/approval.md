VERDICT: HUMAN_REVIEW

## Reasoning
Process was followed: spec approved, builders A, B, C built in parallel and integrated, review round 1 (security PASS, code REWORK x3, ux-ui REWORK x2) fixed by builders D and E, review round 2 PASS. The test result from the orchestrator is 2485 passed, 1 deselected (not rerun here). Round-1 blocking findings are resolved per the round-2 review and the builder reports: non-overlapping mixed frequencies are refused (VAT_FREQUENCY_CONFLICT), W3 compares per rubriek, ICP CSV and PDF now show unassigned EU sales, and the nihil notice is shown only for unfiled periods outside full KOR coverage.

All functional acceptance criteria I could check against the code and reports are met. I am not sending this straight to APPROVE for two reasons, both of which the spec itself flags:
1. The omzet rounding rule (whole euros, toward zero) is marked in the spec as "verify before use" against the current Belastingdienst form. It is implemented in one helper (`round_whole_cents` in `app/domain/vat/report.py`) with an ASSUMPTION comment. A human needs to confirm it against the form before the first real filing, because a wrong rule would be frozen by the irreversible lock.
2. The ICP CSV format is not verified against the portal's upload format. The spec says the CSV is documented as for use in Excel and the PDF is the fallback. The UI must not claim official import compatibility; this should be checked on the screen.

Filing locks periods irreversibly, so the human should see the flow once before it is relied on.

## Acceptance criteria check
Section 4.1 Report computation
- 1 build_vat_report returns VatReport with int cents: met
- 2 grondslag per rubriek from vat-coded lines: met
- 3 BTW from BTW-account lines (3100/3110/3120/3140, 3130 for 2a/4a/4b, 1400/1410 for 5b), 5a/5b/5c/5g totals: met
- 4 rounding down to whole euros for grondslag, btw in cents, unrounded kept for drill-down: met (assumption flagged, see above)
- 5 warnings W1-W8 with plain Dutch messages: met (W3 corrected in round 2; extra codes added and documented)
- 6 empty period gives zeros and "Geen btw in deze periode", can be filed as nihil: met
- 7 sign convention Te betalen / Terug te vragen / Niets te betalen: met

Section 4.2 Periods, frequency, deadlines
- 8 VatPeriod quarter/month, period_range: met
- 9 frequency setting, change refused on conflicts with filed returns: met (round 2 added the kind-conflict check)
- 10 deadline last day of the month after the period, tijdig/te laat relative to injectable clock: met
- 11 overview with status and amount: met in substance. The status word on the aangifte page is "Voorlopig" instead of "Concept" (builder B's deviation, to avoid a glossary detect clash). The overview table still says "Concept". Minor wording inconsistency, not blocking.

Section 4.3 ICP-opgaaf
- 12 per klant totals for EU_GOEDEREN / EU_DIENSTEN, driehoek shown as 0: met
- 13 klant resolution order (invoice buyer, coupling, none to "Nog geen klant gekoppeld"): met
- 14 zero-net klanten omitted, NL or missing btw-nummer listed as "Onvolledig" with fix text: met (per the spec's wording and builder reports; not individually re-read)
- 15 same period as the aangifte, frozen with snapshot: met
- 16 couple_entry_contact refused for locked entries/filed returns: met per reports
- 17 ICP total equals 3b grondslag, with an explicit difference warning: met per reports

Section 4.4 KOR
- 18 kor_from/kor_until with boundary and ordering checks: met (VAT_KOR_START_INVALID, VAT_KOR_DATES)
- 19 full-KOR period: no filing, ICP still available: met
- 20 partial KOR: warning KOR_PARTIAL, report stays available: met
- 21 W8 for full-KOR periods with btw lines: met
- 22 KOR_LIMIT_CENTS shown as information, no enforcement: met

Section 4.5 Filing and locking
- 23 file_vat_return checks: months exist, no double filing, not fully KOR, filed_on not in future; flush only: met
- 24 order check with VAT_EARLIER_NOT_FILED: met
- 25 status, filed_on, reference and JSON snapshot stored: met
- 26 append-only table with triggers, reference settable once: met (migration test covers triggers)
- 27 PERIOD_LOCKED unchanged: met
- 28 update_vat_code lock unchanged: met
- 29 confirmation page, nothing filed by GET, "Dit kun je niet terugdraaien.": met. Round-1 nice-to-have not taken up: the confirm page gives the number of months to be locked, not their names. Non-blocking.
- 30 btw_id required for filing, concept works without: met

Section 4.6 Export
- 31 PDF with the required content and disclaimer, deterministic: met (reportlab invariant=1; content not re-read)
- 32 rubrieken CSV, `;`, BOM, decimal comma, injection prefix: met
- 33 ICP CSV columns as specified: met (format unverified, see above)
- 34 concept and ingediend exports, filenames: met
- 35 format_euro for UI/PDF, own CSV formatter: met

Section 4.7 Web and plain language
- 36 routes present (overview, aangifte, drilldown, klant POST, indienen GET/POST, pdf/csv downloads, settings): met per builder reports and route wiring in app/web/routes.py
- 37 404 for invalid period, plain-Dutch 4xx: met
- 38 POSTs under SameOriginMiddleware, autoescape, filenames from validated ints: met (security review PASS)
- 39 glossary terms btw_aangifte, icp_opgaaf, grondslag, ingediend, nihilaangifte, factuurstelsel added and kor updated: met (verified in app/domain/glossary.py). Usage in templates is enforced by test_every_glossary_key_is_used, which the suite passed.
- 40 defaults (current quarter preselected, today as filed-on date, klant suggestion): met per reports
- 41 plain-Dutch error codes: met (all listed codes present, plus extras)
- 42 rubrieken with number and plain label, 5g as "Te betalen"/"Terug te vragen": met
- 43 /btw placeholder replaced via LEDGER_KEYS: met

## Outstanding issues
- Omzet rounding rule not verified against the Belastingdienst form (spec risk 5). Flagged, one-helper change if wrong.
- ICP CSV format not verified against the portal's import format (spec risk 6). The UI must not claim import compatibility.
- Visual layout, mobile rendering and htmx behaviour (coupling partial, confirm flow) were not verified in a browser. The ux-ui reviewer reports the browser check was blocked by a sandbox error.
- Minor: status wording "Voorlopig" on the aangifte page vs "Concept" in the overview.
- Non-blocking nice-to-have from round 1: the confirm page names counts, not the months.
- Test suite result is taken from state.md (2485 passed, 1 deselected). Not rerun, per instructions.

## What the human should look at
1. Confirm the whole-euro rounding (toward zero) for the omzet fields against the current aangifte form, and the BTW-amounts-in-cents rule. The assumption is documented in `round_whole_cents`.
2. Check the ICP CSV columns against the upload format the Belastingdienst portal accepts, or confirm the PDF and manual copy are the intended path.
3. Open /btw in a browser at phone and desktop width: overview, an aangifte page with warnings, the drill-down, the ICP coupling (htmx swap), and the indienen confirmation. Check that the "Dit kun je niet terugdraaien" text is prominent enough.
4. Decide whether "Voorlopig" or "Concept" should be the one status word used everywhere.
5. Filing locks periods irreversibly. Try it once on a test period before relying on it for a real aangifte.

STATUS: DONE
