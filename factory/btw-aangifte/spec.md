Status: APPROVED

# Spec: btw-aangifte (BTW-aangifte, ICP-opgaaf, KOR, export, vergrendelen na indienen)

## 1. Goal and context

Build the screen and domain logic that turns the booked journal lines into the periodic BTW-aangifte
(omzetbelasting) for an eenmanszaak/VOF: per kwartaal or per maand, split by rubriek, with the
ICP-opgaaf (intracommunautaire prestaties) for EU sales, correct handling of verlegd / EU / export,
an optional KOR (kleineondernemersregeling) setting, an export the user can use to fill in the
Belastingdienst portal, and locking of the covered periods once the user marks the aangifte as
"ingediend".

The program does NOT send anything to the Belastingdienst. The user files in Mijn Belastingdienst
Zakelijk (or via their own software) and uses our overview/export as source. After that the user
marks the aangifte "ingediend" here, which locks the periods.

### What exists today (verified in the code)
- `VatCode` (`app/models/ledger.py`): `code`, `rate_bp`, `sales_rubriek`, `purchase_rubriek`,
  `is_active`, `is_system`. Seeded codes: GEEN, NL_21, NL_9, NL_0, VERLEGD, EU_GOEDEREN, EU_DIENSTEN,
  EXPORT with rubriek mapping in `app/seed/vat_rubrieken.py` (e.g. EU_GOEDEREN = sales 3b / purchase 4b,
  VERLEGD = sales 1e / purchase 2a, EXPORT = 3a / 4a).
- `app/domain/vat/rubrieken.py`: rubriek catalogues (`SALES_RUBRIEKEN`, `PURCHASE_RUBRIEKEN`),
  `ALSO_INPUT_VAT = {"2a","4a","4b"}` (these also create voorbelasting in 5b; "no logic here"),
  and `app/domain/vat/service.py::rubriek_for(session, vat_code, direction)` as hook.
- `JournalLine.vat_code` marks the **grondslag line** (the omzet/kosten line, net amount). The BTW
  amount itself is a **separate line without vat_code** on a BTW account:
  `3100` BTW af te dragen hoog (21%), `3110` laag (9%), `3120` overig, `3130` verlegd af te dragen,
  `3140` privégebruik, `3150` rekening-courant (Belastingdienst), `1400` voorbelasting,
  `1410` verlegd voorbelasting (`app/seed/rgs_accounts.py`). Verkoopfacturen
  (`app/domain/sales/entries.py`) and inkoopfacturen (`app/domain/purchase/booking.py`) book exactly this way.
- Sales and purchase flows only support NL_21/NL_9/NL_0/GEEN (VERLEGD, EU_*, EXPORT are
  `UNSUPPORTED_VAT` there). Verlegd/EU/export therefore enter the ledger only through **manual
  boekingen** (`/boeken`, ledger entry form), possibly with `vat_code` on the grondslag line and amounts
  on 3130/1410. This feature must report those correctly but does not change the invoice flows.
- Periods: `FiscalYear` (calendar year) with 12 monthly `Period` rows (`status` open|locked, `locked_at`).
  `lock_period(session, period_id)` (`app/domain/ledger/service.py`) locks a month and closes the
  fiscal year automatically when all 12 are locked. `_find_period` already rejects posting into a
  locked period (`PERIOD_LOCKED`), and storno/reversal also needs an open period. Locking is
  irreversible by design ("terugdraaien kan niet"). `update_vat_code` already refuses rubriek changes
  for codes used in a locked period.
- `JournalEntry.source_type/source_id` and `SalesInvoice.journal_entry_id` (+ `buyer_btw_number`,
  `buyer_country`, `contact_id`) link entries to relations. `Contact` has `btw_number`, `country`.
- `CompanyProfile.btw_id` (NL...B01 validated) and legal name exist.
- Glossary (`app/domain/glossary.py`) already has: btw, btw_code, rubriek, verlegd, voorbelasting, kor,
  vergrendelen, periode, btw_af_te_dragen, btw_rekening_courant, btw_id. Nav item "BTW" (`/btw`,
  glossary key `btw`) currently renders the placeholder page.

## 2. Non-goals
- No electronic filing: no Digipoort/XBRL/SBR submission, no DigiD/eHerkenning. Export is for
  copying/printing/uploading by the user.
- No changes to the sales/purchase invoice flows (VERLEGD, EU_*, EXPORT stay "manual boeking only").
- No kasstelsel / no btw on betaling: the aangifte is on **factuurstelsel**, by `booking_date`.
- No suppletie (correctie of an already filed aangifte) workflow, no "naheffing/boete" logic.
  Corrections after filing are booked (storno/correction) in an open period and show up in that
  period's aangifte; the UI says so in plain Dutch.
- No automatic payment/bank matching of the BTW payment, no BTW-betaling boeking (the user books it
  as a normal bank mutation on 3150).
- No OSS/IOSS (rubriek 3c / afstandsverkopen) calculation beyond showing it as a rubriek line from
  vat codes; no kleine-ondernemersregeling for EU-sales thresholds.
- No voorlopige teruggaaf, no investeringsaftrek, no privégebruik wizard (1d shows what is booked on 3140).
- No BV features.

## 3. User stories
1. As ondernemer I open BTW and see per kwartaal (or maand) whether the aangifte is open, concept or
   ingediend, with deadline and the amount to pay/receive, so I know what to do next.
2. I open a concept aangifte and see all rubrieken in the same order and wording as the Belastingdienst
   form, each with a plain-Dutch label, so I can copy the numbers into Mijn Belastingdienst.
3. I click a rubriek and see the boekingen behind it (drill-down), so I can check or correct them.
4. I get warnings in plain Dutch for things that probably are wrong (btw-regel without grondslag,
   BTW-bedrag that does not match the tarief, EU-verkoop without btw-nummer of klant, a vergrendelde
   periode, an earlier period not yet ingediend).
5. For EU sales (3b) I see the ICP-opgaaf: per klant (landcode + btw-nummer) the bedrag for goederen
   and diensten, and I can couple a klant to a boeking that has none.
6. I can set my frequency (kwartaal/maand) and, if applicable, that I use the KOR from a date on.
7. I can download/print the aangifte (PDF), a CSV of rubrieken, and the ICP-opgaaf as CSV.
8. When I have filed in the portal I click "Markeer als ingediend": the covered periods are locked
   (with a clear, irreversible confirmation), and the numbers are frozen as a snapshot.

## 4. Acceptance criteria

### 4.1 Report computation (domain, pure + DB)
Definitions: *signed sales amount* of a line = credit - debit; *signed purchase amount* = debit - credit.
A line is on the **sales side** when its vat code has `sales_rubriek` and the line is on an account of
type `revenue`; otherwise on the **purchase side** when the vat code has `purchase_rubriek` (accounts of
type `expense`/`asset`). Lines without vat_code or whose code has no rubriek for their side are not
part of the aangifte (code GEEN, NL_0 purchase). Ambiguous lines (code has both rubrieken and account
type is neither revenue nor expense/asset) are reported as a warning, not guessed.
Storno entries are normal entries with swapped sides, so signed sums net out automatically; reporting
uses `booking_date` of each entry, including opening-kind entries? **No: `kind='opening'` entries are
excluded** (they carry balances, not transactions).

1. `build_vat_report(session, start, end)` returns a `VatReport` for a date range; all amounts are int cents.
2. **Grondslag** per rubriek = sum of signed amounts of vat-coded lines in the range, grouped by the
   line's rubriek (sales rubriek for sales-side lines, purchase rubriek for purchase-side lines).
3. **BTW amounts** are taken from the BTW-account lines (lines without vat_code on the mapped accounts),
   not recomputed from the rate, so they equal what is printed on the invoices:
   - 1a = net credit on 3100; 1b = net credit on 3110; 1c = net credit on 3120; 1d = net credit on 3140.
   - 2a/4a/4b (verlegd, inkoop uit EU/buiten EU): the net credit on 3130 of an entry is attributed to the
     purchase-side verlegd rubriek (2a, 4a or 4b) found on that same entry. If an entry has more than one
     of these rubrieken, the BTW goes to the rubriek with the largest absolute grondslag and a warning is
     added ("Deze boeking bevat meerdere verlegde soorten...").
   - 3a, 3b, 1e, 3c: BTW is always 0 (no BTW amount is shown).
   - 5b (voorbelasting) = net debit on 1400 + net debit on 1410 (includes the voorbelasting that belongs
     to 2a/4a/4b; `ALSO_INPUT_VAT` documents this). 5a (verschuldigde btw) = 1a+1b+1c+1d+2a+4a+4b btw.
     5c = 5a - 5b (subtotaal). 5g = 5c (no 5d/5e/5f in this version; KOR-vermindering excluded, see 4.4).
   - Rubriek order and labels come from `rubrieken.py`; add the totals rows 5a, 5b, 5c, 5g with plain labels.
4. **Rounding for display and export** (as in the Belastingdienst form): grondslag per rubriek rounded
   **down to whole euros** (`cents // 100 * 100`, per sign: use floor toward zero for positives; negative
   amounts, e.g. creditnota's, round toward zero as well and never produce -0); BTW amounts stay in cents.
   The unrounded cents are kept in the report for drill-down.
5. **Controle (warnings)**, each as `VatWarning(code, message, entry_ids)` in plain Dutch with an action:
   - W1 grondslag line with a taxable code (rate > 0) in the range but no BTW amount line in the same entry
     ("Er staat btw-grondslag zonder bijbehorende btw-boeking...").
   - W2 BTW-account line without any vat-coded line in the same entry.
   - W3 BTW amount deviates more than €0,05 per entry/rubriek from `grondslag * rate` for codes with a
     rate > 0 (rounding differences up to 5 cent per entry are allowed).
   - W4 sales line with vat code 3b/3a/EU_* etc. on 3b without a coupled klant (see 4.3).
   - W5 verlegd/EU purchase line (2a/4a/4b) without a matching 3130 credit and 1410 debit of equal size.
   - W6 an earlier period in the same fiscal year has entries but its aangifte is not ingediend.
   - W7 the range contains entries with `vat_code` whose code is inactive/unknown (should not occur) .
   Warnings never block the concept; they block nothing except where 4.5 says otherwise.
6. An empty period (no relevant lines) yields all zeros, 5g = 0 and the message "Geen btw in deze periode";
   it can still be marked ingediend (nihilaangifte).
7. Sign convention: 5g > 0 -> "Te betalen", 5g < 0 -> "Terug te vragen", 0 -> "Niets te betalen".

### 4.2 Periods, frequency, deadlines
8. A **return period** (`VatPeriod`) is `(year, kind, number)` with kind `quarter` (1-4) or `month` (1-12);
   `period_range()` gives start/end dates; quarter = 3 monthly `Period` rows.
9. Frequency setting `quarter` (default) | `month`, stored in the new `vat_setting` row; changing it is
   only allowed for a **future** boundary: it is refused (plain Dutch) when it would create overlap or a
   gap with already ingediende aangiftes in that year (e.g. month returns exist while switching to
   quarter in the same year). Per fiscal year a single kind is used once any aangifte of that year is ingediend.
10. Deadline = last day of the month after the period (kwartaal Q1 -> 30 april, month -> end of next month);
    shown with "tijdig" / "te laat" relative to today (injectable clock). No fines computed.
11. The BTW overview page lists the aangiftes of the selected boekjaar for the chosen frequency with
    status: `nog niet gestart` (no entries and not filed), `concept`, `ingediend`; plus amount from the live
    report (concept) or the snapshot (ingediend).

### 4.3 ICP-opgaaf
12. `build_icp(session, start, end)` returns per klant (landcode + btw-nummer, normalised uppercase, no
    spaces) the totals in whole... in cents: `goederen_cents` for vat code `EU_GOEDEREN`, `diensten_cents`
    for `EU_DIENSTEN` (sales side, rubriek 3b). Other codes mapped to 3b (user-created) go to `goederen`
    with a warning "soort onduidelijk"; the report separates `driehoek` = 0 (not supported, shown as 0).
13. The klant of an entry is resolved in this order: (a) `SalesInvoice.journal_entry_id == entry.id` ->
    `buyer_btw_number`/`buyer_country`; (b) a row in the new `vat_entry_contact` (entry_id -> contact_id)
    -> `Contact.btw_number`/`country`; (c) none -> the entry is listed under "Nog geen klant gekoppeld".
14. Lines that net to 0 per klant are omitted. A klant without btw-nummer or with country `NL` is listed
    under "Onvolledig" with a plain-Dutch fix ("Vul het btw-nummer van de klant in bij Relaties").
15. The ICP-opgaaf is for the same period as the aangifte (kwartaal, or maand if the user has to file
    per maand; an ICP-opgaaf has no separate lock: it freezes with the aangifte snapshot).
16. Coupling a klant: `couple_entry_contact(session, entry_id, contact_id)` inserts/replaces a row in
    `vat_entry_contact`; refused for entries in a **vergrendelde** period or an ingediende aangifte
    (plain Dutch). This table is the only thing that can change for a booked entry and it is not part
    of the append-only ledger.
17. Total goederen+diensten of the ICP equals the (unrounded) grondslag of rubriek 3b (a mismatch is
    shown as a warning "ICP en rubriek 3b komen niet overeen" with the difference; unattached entries count in the
    difference-free "Nog geen klant gekoppeld" bucket, so equality holds when all are listed).

### 4.4 KOR
18. `vat_setting.kor_from` (date, nullable) and `kor_until` (date, nullable). Setting KOR requires a
    start date on the first day of a quarter or month boundary of the chosen frequency; ending it requires `kor_until >= kor_from`.
    Dates are free to be in the past (retroactive correction is the user's responsibility) but a change is
    refused when it touches a period that is already ingediend.
19. For a period fully inside the KOR range: the page shows "Je gebruikt de KOR: je hoeft geen btw-aangifte
    te doen" and no aangifte can be marked ingediend for it (plain error). The ICP-opgaaf is still available
    (KOR-ondernemers dienen wel ICP in bij EU-leveringen).
20. For a period partially in the KOR range: warning, report remains available; the user decides.
21. Warning W8 for periods inside KOR: any BTW-account line exists in the range ("Je gebruikt de KOR maar
    er staat btw in je boekingen ...").
22. The KOR omzetgrens (€20.000/jaar) is displayed as information only (`KOR_LIMIT_CENTS = 2_000_000`)
    with the year's omzet (rubrieken 1a-1e+3a+3b) as a hint; no enforcement.

### 4.5 Marking as ingediend + locking
23. `file_vat_return(session, vat_period, *, filed_on, reference=None)` (flushes, never commits) requires:
    all monthly `Period` rows covering the range exist; none of them is already part of another ingediende
    return; not fully inside KOR; `filed_on <= today`. It then, in one transaction:
    (a) builds the report + ICP once, (b) stores a snapshot, (c) calls `lock_period` for every month in the range.
24. Order check: filing is **refused** if an earlier return of the same year kind has entries but is not
    ingediend (error: "Dien eerst de aangifte over <periode> in, daarna deze."). Exception: no entries before.
25. After filing, `status='ingediend'`, `filed_at`, `filed_on` (the date the user filed in the portal) and
    optional `reference` (ontvangstbevestiging nummer) are stored; the snapshot (all rubriek lines, totals,
    ICP rows, warnings) is stored as JSON and is what the page and exports show from then on, even if the
    ledger later changes (it cannot, periods are locked; storno in a later period shows in that later aangifte).
26. An ingediende return can **not** be un-filed or edited; the table is append-only (SQLite triggers like
    `bank_match` in migration 0011: no DELETE, UPDATE only allowed to set `reference` once if NULL). The
    locking is the existing irreversible `lock_period`.
27. Posting or storno into a locked period keeps failing with the existing `PERIOD_LOCKED` message; the
    BTW page explains where to correct (book a correction in the current open period).
28. `update_vat_code` rubriek lock for codes in locked periods is unchanged (already implemented).
29. Filing needs the user's explicit confirmation page that lists the periods being locked and states
    "Dit kun je niet terugdraaien." Nothing is filed by GET.
30. Filing requires the company `btw_id` to be set (plain Dutch hint -> Instellingen > Bedrijfsgegevens)
    because the exports show it; the concept page works without it.

### 4.6 Export
31. **PDF** (reportlab, same style as `sales/pdf.py`, pure function on a snapshot dataclass, deterministic
    bytes): "BTW-aangifte <periode>" with company name, btw-id, period, status, all rubrieken (grondslag
    whole euros, BTW cents), 5a/5b/5c/5g, the ICP table, and the text "Dit is een overzicht om over te
    nemen in Mijn Belastingdienst Zakelijk; het is zelf geen aangifte."
32. **CSV rubrieken**: `;`-separated, UTF-8 with BOM (Excel NL), columns `rubriek;omschrijving;omzet;btw`,
    amounts as `1234,56` (decimal comma, no thousands separator), one row per rubriek with values,
    followed by 5a, 5b, 5c, 5g rows. Cells starting with `= + - @` in text fields are prefixed with `'` (CSV injection).
33. **CSV ICP**: `;`-separated, UTF-8 with BOM: `landcode;btw_nummer;goederen;diensten;driehoek`, whole euros,
    one row per klant (btw-nummer without landcode prefix in its own column, landcode separate).
34. Exports are available for concept (watermark/label "CONCEPT") and ingediend (from snapshot).
    Filenames: `btw-aangifte-2026-Q3.pdf`, `btw-aangifte-2026-Q3-rubrieken.csv`, `btw-icp-2026-Q3.csv`.
35. Money formatting uses `app.domain.money.format_euro` for UI/PDF; CSV uses its own decimal-comma formatter
    (tested), never floats.

### 4.7 Web / plain-language (CLAUDE.md)
36. Routes (all under `/btw`, nav item "BTW" already exists):
    - `GET /btw` overview of the year (query `?jaar=`), frequency/KOR status, list of aangiftes.
    - `GET /btw/{year}/{kind}/{number}` aangifte page (concept or ingediend) with rubrieken, warnings, ICP section.
    - `GET /btw/{year}/{kind}/{number}/rubriek/{rubriek}` drill-down: entries/lines behind the rubriek (reuses entry links `/boeken/<id>`).
    - `POST /btw/{year}/{kind}/{number}/klant` couple klant to entry (HTMX partial for ICP).
    - `GET .../indienen` confirmation page; `POST .../indienen` files + locks, redirects (303) to the aangifte page.
    - `GET .../pdf`, `GET .../rubrieken.csv`, `GET .../icp.csv` downloads.
    - `GET/POST /instellingen/btw-aangifte` settings: frequency and KOR (add to `SETTINGS_NAV` under "Boekhouding", label "BTW-aangifte", term key `btw_aangifte`).
37. Invalid year/kind/number -> 404 page; invalid input -> 4xx with a plain-Dutch message, never a traceback or raw code.
38. All POSTs are protected by the existing `SameOriginMiddleware`; templates autoescape; download filenames are built from validated ints only.
39. Terms introduced and their glossary entries (all in `app/domain/glossary.py`, plain Dutch first; each
    used in a template via `info()` / `term_label`, and every key must appear on some page because
    `tests/test_plain_language.py::test_every_glossary_key_is_used` enforces it):
    - `btw_aangifte` "BTW-aangifte" / "Opgave van je btw aan de Belastingdienst"
    - `icp_opgaaf` "ICP-opgaaf" / "Overzicht van je verkopen aan bedrijven in de EU"
    - `grondslag` "Grondslag" / "Het bedrag waarover btw wordt berekend"
    - `ingediend` "Ingediend" / "Aangifte is verstuurd"  (covers "Markeer als ingediend")
    - `nihilaangifte` "Nihilaangifte" / "Aangifte zonder btw-bedragen"
    - `factuurstelsel` "Factuurstelsel" / "Btw telt op factuurdatum"
    - `intracommunautair` is not a separate term: use "EU-verkoop" in the UI and explain `icp_opgaaf`.
    - existing keys reused: btw, rubriek, verlegd, voorbelasting, kor (update its text: "...Je doet dan geen
      btw-aangifte, maar wel een ICP-opgaaf bij EU-leveringen"), vergrendelen, periode, btw_af_te_dragen.
    - New glossary entries use `detect` regexes only where the term is plain text on screens; otherwise `(_NEVER,)` like neighbours.
40. Suggested defaults on screen: current open kwartaal preselected; frequency default kwartaal; filed-on
    date prefilled with today; klant for ICP suggested from the entry's description if a relation name
    matches (`Contact.name_key`), user confirms.
41. Plain-Dutch messages (domain errors, each a `LedgerError`-style code + message; add the codes to
    `app/domain/errors.py`):
    - `VAT_PERIOD_INVALID`: "Deze periode bestaat niet. Kies een kwartaal van 1 tot 4 of een maand van 1 tot 12."
    - `VAT_PERIOD_MISSING`: "Het boekjaar {year} bestaat nog niet. Maak het eerst aan onder Instellingen > Boekjaren."
    - `VAT_ALREADY_FILED`: "Deze aangifte is al ingediend en kan niet meer worden aangepast."
    - `VAT_EARLIER_NOT_FILED`: "Dien eerst de aangifte over {periode} in, daarna deze."
    - `VAT_KOR_NO_RETURN`: "Je gebruikt de KOR in deze periode, dus je hoeft geen btw-aangifte te doen."
    - `VAT_COMPANY_INCOMPLETE`: "Vul eerst je btw-nummer in onder Instellingen > Bedrijfsgegevens."
    - `VAT_FREQUENCY_CONFLICT`: "Je kunt niet wisselen tussen kwartaal en maand in {year}: er is al een aangifte ingediend."
    - `VAT_ENTRY_LOCKED`: "Deze boeking zit in een vergrendelde periode, dus je kunt er geen klant meer aan koppelen."
    - `VAT_FUTURE_DATE`: "De datum van indienen kan niet in de toekomst liggen."
    - `VAT_KOR_DATES`: "De einddatum van de KOR ligt vóór de startdatum."
42. Screens mark rubrieken with both the plain label and the number (e.g. "Omzet met 21% btw (1a)").
    Totals row 5g reads "Te betalen" / "Terug te vragen" with the amount, never only "5g".
43. The placeholder for `/btw` is replaced by the real page: `btw` removed from placeholder routing by
    adding `"btw"` to `LEDGER_KEYS` in `app/web/routes.py`.

## 5. Technical approach

### 5.1 Data model (Alembic migration `0014_btw_aangifte.py`, down_revision `0013_bank_match_sales`; no `app.models` import in the migration)
- `vat_setting` (single row, `CHECK id = 1`): `frequency` ('quarter'|'month', default 'quarter'),
  `kor_from` Date NULL, `kor_until` Date NULL, `updated_at`. Created lazily on first save; absence = defaults.
- `vat_return`: `id`, `year` int, `kind` ('quarter'|'month'), `number` int (CHECK ranges per kind),
  `start_date`, `end_date`, `status` ('ingediend') — only filed returns are stored; concept is computed live —
  `filed_on` Date, `filed_at` DateTime, `reference` String NULL, `snapshot_json` Text NOT NULL,
  `total_cents` Integer (5g), UNIQUE(`year`,`kind`,`number`). Triggers: no DELETE; UPDATE only to set
  `reference` when it was NULL (all other columns `IS` unchanged), same pattern as `bank_match` in 0011.
  Also overlap protection in domain code (a range may not overlap an existing return).
- `vat_entry_contact`: `entry_id` PK FK journal_entry, `contact_id` FK contact, `updated_at`.
- Models in `app/models/vat_return.py` (`VatSetting`, `VatReturn`, `VatEntryContact`), exported from
  `app/models/__init__.py`.
- Migration test must cover: upgrade from 0013, downgrade, triggers block delete/update.

### 5.2 Domain (`app/domain/vat/`, business logic only here)
New modules (existing `service.py`, `rubrieken.py`, `rates.py` stay; `__init__.py` re-exports the new public API):
- `periods.py` (pure): `VatPeriod(year, kind, number)`, `period_range()`, `months()`, `deadline()`,
  `quarter_of()`, `periods_of_year(year, kind)`, `previous(period)`, validation (`VAT_PERIOD_INVALID`).
- `report.py`: dataclasses `RubriekLine(rubriek, side, label, grondslag_cents, grondslag_whole_cents, vat_cents)`,
  `VatWarning(code, message, entry_ids)`, `VatReport(period_start, period_end, lines, totals{5a,5b,5c,5g}, warnings, direction)`;
  `build_vat_report(session, start, end)` doing a single SQL pass over `journal_line` join `journal_entry`
  (exclude `kind='opening'`) join `account` join `vat_code`, then pure aggregation in a testable function
  `aggregate(rows, rubriek_catalogue) -> VatReport` (pure part tested without DB); `drilldown(session, start, end, rubriek)`.
  Account-to-rubriek mapping constants: `BTW_ACCOUNT_RUBRIEK = {"3100":"1a","3110":"1b","3120":"1c","3140":"1d"}`,
  `VERLEGD_PAYABLE = "3130"`, `INPUT_ACCOUNTS = ("1400","1410")` (referenced by account **code**, not id).
- `icp.py`: `IcpRow`, `IcpReport`, `build_icp(session, start, end)`, `couple_entry_contact(...)`,
  `suggest_contact(session, entry_id)`; btw-nummer normalisation (reuse relations validation if present, else strip spaces + upper).
- `settings.py`: `get_vat_settings`, `save_vat_settings(session, frequency, kor_from, kor_until, today)`,
  `is_kor(period, settings)` -> 'none'|'partial'|'full', `KOR_LIMIT_CENTS`.
- `filing.py`: `list_returns(session, year, kind)` -> overview rows with status/deadline/amount,
  `get_return(session, period)`, `file_vat_return(...)` (calls `ledger.lock_period`), snapshot (de)serialization
  to JSON with only ints/strings (no floats), `FiledReturn` dataclass.
- `export.py` (pure, no DB): `rubrieken_csv(snapshot) -> bytes`, `icp_csv(snapshot) -> bytes`, `format_csv_cents`,
  `aangifte_pdf(snapshot) -> bytes` (reportlab, `invariant=1`).
- Shared dataclass contract between parts (**frozen, define in `report.py`/`filing.py`, do not change without telling the spec writer**):
  `ReturnSnapshot(period: VatPeriod, status: str, company_name: str, btw_id: str|None, lines: list[RubriekLine],
  totals: dict[str,int], icp: list[IcpRow], icp_unassigned: list[...], warnings: list[VatWarning], filed_on: date|None, reference: str|None, is_concept: bool)`.
  `filing.get_snapshot(session, period) -> ReturnSnapshot` returns the stored one for ingediend, a live one otherwise.
  Part C builds on this type only.
- Errors: add the codes in 4.7 to `app/domain/errors.py` using the existing `LedgerError` pattern/`_error_class`.
- Glossary: add terms in 4.7 and update `kor`.
- Clock: all functions that depend on today take `today: date | None = None`.

### 5.3 Flow of filing
`POST indienen` -> route calls `filing.file_vat_return(session, period, filed_on=..., reference=...)`
inside the request session -> route commits; any `LedgerError` -> re-render confirm page with message (4xx).
Because `lock_period` flushes only, a failure rolls back the lock and the snapshot together.

### 5.4 Error handling
Domain raises `LedgerError(code, message)` (existing, see `vat_routes._status_for`); routes map to status codes (404 for unknown period, 409 for conflicts like already filed, 422 for bad input) and render the message in the page, never raw exceptions.

### 5.5 UI
Jinja2 + HTMX, existing partials (`page_header`, `info`, `term_label`, `empty_state`, `partials/_ui.html`). Tailwind/daisyUI classes `d-` allowed (new screens may use them; rebuild with `tools/build-css.sh` if new classes are used and commit `static/tailwind.css`). Mobile layout must pass `tests/test_mobile_css.py`.

## 6. Work breakdown (3 parts, disjoint file ownership)

### Part A — Schema, domain, glossary (no web)
Owns:
- `migrations/versions/0014_btw_aangifte.py`
- `app/models/vat_return.py`, `app/models/__init__.py`
- `app/domain/vat/periods.py`, `report.py`, `icp.py`, `settings.py`, `filing.py`, `__init__.py`
- `app/domain/errors.py` (append only), `app/domain/glossary.py`
- `tests/vat/` new files (`test_periods.py`, `test_report.py`, `test_icp.py`, `test_settings_kor.py`, `test_filing_lock.py`), `tests/test_btw_migration.py`
Produces the public API in 5.2 first (stub signatures + dataclasses committed early so B and C can code against them).
Depends on: nothing. Must not touch `app/web/*`, `export.py`.
TDD first for aggregation, rounding, KOR, filing/locking (money + VAT).

### Part B — Web screens (overview, aangifte page, drill-down, ICP coupling, indienen, settings)
Owns:
- `app/web/btw_routes.py`, `app/web/templates/btw/*` (overview, return page, drilldown, `_icp.html`, confirm, settings)
- `app/web/routes.py` (register router, add `"btw"` to `LEDGER_KEYS`), `app/web/navigation.py` (SETTINGS_NAV item "BTW-aangifte")
- `tests/test_btw_web.py`, additions to `tests/test_plain_language.py` (add the BTW pages to PAGES), `tests/test_mobile_css.py` additions if needed
- optional small CSS in `app/web/static/app.css` (btw- prefixed classes) and `static/tailwind.css` rebuild
Depends on: Part A API (signatures); download links point to Part C routes.
Does not implement PDF/CSV; only links to the download URLs in 4.7.

### Part C — Export (PDF + CSV) and download routes
Owns:
- `app/domain/vat/export.py`
- `app/web/btw_export_routes.py` (the three GET download routes, `APIRouter` named `router`, registered by Part B in `routes.py` via `from app.web.btw_export_routes import router as btw_export_router`; Part B owns that single registration line)
- `tests/vat/test_export.py`, `tests/test_btw_export_web.py`
Depends on: `ReturnSnapshot` and `filing.get_snapshot` from Part A (contract in 5.2).
Integration points: Part B adds the registration line; A's glossary has no export terms (none needed).

Integration order: A (API stubs) -> B and C in parallel -> final integration run of full test suite.

## 7. Test strategy
- Domain (pytest, in-memory SQLite fixture as in `tests/vat/conftest.py`): table-driven tests for
  aggregation per rubriek: NL_21/NL_9 invoice, creditnota, storno netting, verlegd (2a) with 3130/1410,
  EU goederen (3b) and diensten, export (3a), 0%, GEEN, opening entries excluded, rounding down to
  whole euros (e.g. 1234,99 -> 1234; 0,99 -> 0), voorbelasting incl. 1410, 5g sign, nihil.
- Warnings W1-W8 each with a positive and negative case.
- ICP: klant resolution order (sales invoice buyer, coupling, none), normalisation, NL excluded, sum equals 3b.
- KOR: none/partial/full, filing refused, ICP still works, date validation.
- Filing: locks exactly the months of the range, closes fiscal year when Q4 files, refuses double filing,
  refuses out-of-order filing, refuses future date, snapshot unchanged after later ledger changes,
  triggers block delete/update, post/storno into locked period still fails with `PERIOD_LOCKED`,
  rollback leaves periods open when something fails midway.
- Migration test: upgrade/downgrade 0013 <-> 0014 and trigger behaviour.
- Export: CSV decimal comma/BOM/injection prefix/negative amounts, PDF is valid (`%PDF`), deterministic bytes,
  contains period and btw-id text, filenames.
- Web: every route (200/404/303/409), CSRF/same-origin, HTMX partial for coupling, confirm page needs POST,
  plain-language pages added to `tests/test_plain_language.py` PAGES (no missing info icons, no bare terms).
- Full suite (`pytest`) must pass before review.

## 8. Risks and decisions made
1. **Factuurstelsel by booking_date** (decision): matches how invoices are booked; kasstelsel is out of scope. Risk: a user on kasstelsel gets wrong numbers - mitigated by the `factuurstelsel` glossary text.
2. **BTW taken from BTW accounts, grondslag from vat-coded lines** (decision): equals printed invoice totals; risk is manual boekingen that omit one of the two, covered by W1/W2/W3.
3. **Verlegd/EU/export only via manual boekingen** (decision): invoice flows stay unsupported; the aangifte supports them as soon as they are booked. Risk: user confusion why invoices cannot use them - the page may link to the manual booking form with a short hint. Possible follow-up feature.
4. **ICP klant coupling via `vat_entry_contact`** (decision): avoids changing `journal_entry` (append-only ledger). Coupling remains editable until the period is locked.
5. **Rounding rules** (decision, **verify before use**): omzet floor to whole euros, BTW to cents per the current Belastingdienst form. If the form's rule differs, change only `report.py` rounding helper and the PDF/CSV tests. The builder must add a code comment citing this assumption.
6. **ICP CSV format** (decision): the portal's exact upload format is not verified offline; our CSV is documented as "voor overnemen/importeren in Excel" and the PDF is the safe fallback. No claim of official import compatibility in the UI.
7. **Locking is irreversible** (existing behaviour, kept): filing the wrong quarter locks months forever. Mitigations: explicit confirmation page, order check, filed-on date, no auto-filing. Locking Q4 closes the boekjaar automatically (existing `_close_if_all_locked`); the confirm page says so when it applies.
8. **Frequency change mid-year** limited (4.2 #9) to keep gapless coverage.
9. **KOR is informational + guard** (decision): no automatic BTW suppression in invoices; KOR omzetgrens shown, not enforced.
10. **Performance**: single SQL pass per report; datasets are single-user small, no pagination needed except drill-down (reuse existing page size).
11. **Deadline/holiday logic** ignored (decision): deadline shown as last day of next month; weekends/holidays not adjusted.
12. **Glossary test coupling**: `test_every_glossary_key_is_used` requires every new glossary key to be used in a template; Part A adds keys, Part B must use each. A and B coordinate through the key list in 4.7 (B fails its tests otherwise).

No open business questions: all decisions above use sensible defaults.
