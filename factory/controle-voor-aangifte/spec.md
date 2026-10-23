Status: APPROVED

# Spec: Controle voordat je aangifte doet ("Klopt dit?")

Backlog: feature 48 (feature-candidates.md, besluit "opnemen", size M).

## Goal and context
Before a user files a BTW-aangifte they want to know "klopt mijn administratie over deze periode?". Today the aangifte page only shows VAT-specific warnings (`VatWarning`, card "Controleer dit" in `btw/return.html`). Nothing tells the user about bank transactions that were never booked, bookings without a receipt, broken (unbalanced) data, documents still in the inbox, or concept invoices that do not count yet.

Build one pure-domain check service (`app/domain/checks/`) that, for a VAT period, returns a list of checks (count, plain-Dutch explanation, fix link, example items). Show it on a new screen `/controle/{year}/{kind}/{number}` and as a short banner on the BTW-aangifte page and the indienen (confirm) page. The checks warn, they never block filing: the user decides.

## Non-goals
- Not blocking `file_vat_return`; no changes to filing, ledger, bank, inbox or sales logic.
- No new tables or migrations (all checks are read-only queries over existing data).
- No auto-fix, no "dismiss/ignore" state per warning, no email/notification.
- Existing VAT warnings (W2, W4, W6, W7, W8, KOR) stay where they are (card "Controleer dit"); not duplicated in the new checks. The controle page links to the aangifte for them.
- Year-end (jaarcijfers/IB) checks: out of scope.
- The checks are a help, not a guarantee: the page says so.

## User stories
- As a non-accountant I open "Controle" for Q3 and see in plain Dutch what to fix before I file, each with a button that takes me to the right screen.
- As a user on the aangifte page I see "Klopt dit? 3 dingen om te controleren" with a link, or "Alles lijkt in orde".
- As a user on the indienen page I get the same reminder one last time, and can still file.

## Checks (all per VAT period `[start, end]` from `vat.period_range`)
Each check has: `key`, `title` (plain Dutch), `explanation`, `level`, `count`, `items` (max 5 examples, each label + href), `fix_href`, `fix_label`.
Levels: `ok` (count 0), `let_op` (advice), `fout` (needs fixing before filing is sensible).

| key | level when count>0 | what is counted | fix link |
|---|---|---|---|
| `bank_ongeboekt` | fout | `bank_transaction.status = 'nieuw'` with `booking_date` in period (ignored 'genegeerd' and 'geboekt' do not count). Also report total amount in cents of these (sum of abs). | `/bank/afletteren` (status nieuw) |
| `onevenwichtig` | fout | journal entries (any kind) in period whose sum(debit_cents) != sum(credit_cents), plus entries with no lines. Message names the difference: "Debet en credit zijn niet gelijk: er ontbreekt €12,10" (use `app.domain.money` formatting). Normally impossible (ledger enforces it); this is a safety net on the data. | `/boeken/{id}` per item |
| `boeking_zonder_document` | let_op | entries in period with `kind='normal'`, `source_type IS NULL` (manual/bank direct bookings; NOT `verkoopfactuur`, `beginbalans`, storno), journal type not `memoriaal`, with at least one line on an account of type `expense` or `revenue`, and no `document.journal_entry_id = entry.id`. Purchase bookings (`inkoopfactuur`) always have a document and sales invoices have their own PDF, so they are excluded. | `/boeken/{id}` per item |
| `inbox_ongeboekt` | let_op | `document.status IN ('nieuw','herkend')` with `received_at` date <= period end (any age). | `/inbox` |
| `concept_facturen` | let_op | `sales_invoice.status = 'concept'` with `invoice_date <= end`. Explain: "Een conceptfactuur telt nog niet mee in je btw." | `/verkoop/{id}` per item, list at `/verkoop` |

Overall verdict: `fout` if any check is fout, else `let_op` if any, else `ok`. Texts: ok = "Alles lijkt in orde. Dit is een hulpmiddel, geen garantie."; otherwise "N dingen om te controleren".

## Acceptance criteria
1. `checks.run_checks(session, period, *, today=None) -> CheckReport` exists in `app/domain/checks/` (pure queries, no web imports), exported from `app/domain/checks/__init__.py`. Money is integer cents everywhere.
2. Each check in the table above returns the right count/level/items for a period and ignores data outside it (bank transactions and entries by date; inbox and concept invoices as stated).
3. With no data, all five checks are `ok`, verdict `ok`.
4. A storno'd or opening entry and an `inkoopfactuur`/`verkoopfactuur` entry never appear in `boeking_zonder_document`; a manual expense booking with a linked document does not appear either.
5. `onevenwichtig` is tested by inserting unbalanced lines directly via SQL/ORM (bypassing the ledger service).
6. Route `GET /controle` redirects (303) to the current VAT period (`vat.period_for_date(today, vat.kind_for_year(...))`); `GET /controle/{year}/{kind}/{number}` renders the checklist; invalid period gives the standard 404 (`web.not_found_response`).
7. The page lists the checks, problems first, each with a status badge (Klopt / Let op / Fout), count, explanation, up to 5 example links and a fix button; an "alles in orde" check is shown collapsed/quiet as "Klopt". Includes a period switcher (previous/next period) and a link "Terug naar de btw-aangifte".
8. Sidebar: nav item "Controle" (label), group 2 ("Aangifte en overzicht"), `term_key="controle_aangifte"`, path `/controle`, placed right after "BTW"; `is_active` works for sub-paths.
9. `btw/return.html` (when not filed) shows a banner above the "Controleer dit" card: verdict text plus link to `/controle/{period}`. Filed returns show no banner. `btw/confirm.html` shows the same banner plus the non-blocking sentence "Je kunt toch indienen als je zeker weet dat het klopt." Filing still works with warnings present.
10. All page text is Dutch, plain-language first. Errors/messages say what is wrong and what to do (e.g. "Er staan 4 bankmutaties in deze periode die je nog niet hebt verwerkt. Verwerk ze eerst, anders ontbreekt er btw in je aangifte.").
11. Plain-language requirement (CLAUDE.md): new glossary entries in `app/domain/glossary.py` (see below), shown with `info()` next to the term on the new page, banner and nav; the new page(s) are added to `PAGES` in `tests/test_plain_language.py` and pass; glossary unit tests still pass (explanation <= 220 chars, unique keys, no unused keys beyond the allowed staged list).
12. No write happens on any of the routes (GET only; no session commit).

### Terms and glossary entries (check existing keys first, e.g. `transactie`, `afletteren`, `btw`, reuse instead of duplicating)
- `controle_aangifte`: term "Controle voor aangifte", plain "Klopt dit?"; explains it checks the period for loose ends before filing, never blocks, no guarantee.
- `ongeboekte_transactie`: term "Ongeboekte transactie", plain "Bankmutatie die je nog niet hebt verwerkt".
- `bon_bij_boeking`: term "Boekingsstuk", plain "Bon of factuur bij een boeking"; 7 jaar bewaren (bewaarplicht) in one sentence.
- `onevenwichtige_boeking`: term "Onevenwichtige boeking", plain "Boeking die niet klopt"; debet en credit moeten gelijk zijn.
- `conceptfactuur`: term "Conceptfactuur", plain "Factuur die nog niet definitief is"; check whether the sales screens already have a term and reuse.
Use `detect` regexes or `_NEVER` consistent with neighbouring entries so the plain-language test does not demand icons on generic words.

### Suggested defaults
Default period = current VAT period (per `kind_for_year`); if the current period is already filed, the most recent unfiled period with data is NOT searched: keep it simple and use the current period.

## Technical approach
Package `app/domain/checks/`:
- `types.py`: frozen dataclasses `CheckItem(label: str, href: str)`, `Check(key, title, explanation, level, count, items: tuple[CheckItem, ...], fix_href, fix_label, amount_cents: int | None = None)`, `CheckReport(period: VatPeriod, checks: tuple[Check, ...])` with properties `verdict` ("ok"|"let_op"|"fout"), `problem_count` (number of checks with level != ok), `headline` (plain-Dutch string).
- `service.py`: `run_checks(session, period, *, today=None)` calling one private function per check; shared helper builds a `Check` from count/items. Hrefs are built in the domain as plain strings (`/boeken/{id}` etc.), as the vat domain already does for rubriek links; use constants for the URL prefixes so routes can import none of it.
- Use SQLAlchemy `select` with `func.sum`/`group_by`/`having` (unbalanced) and `exists` (document link); no per-row Python loops over all entries.
- Item labels: entry number + description + date + amount where relevant, formatted with the existing money helper.

Web: `app/web/controle_routes.py` (parse path -> `vat.VatPeriod` as `btw_routes._parse_period` does, call `run_checks`, render `controle/index.html`); register the router in `app/main.py` like the others. Template `app/web/templates/controle/index.html` plus a partial `controle/_banner.html` (verdict + link) that btw templates `{% include %}` with `report` in context. `btw_routes._return_page` and `_confirm_page` add `controle=checks.run_checks(session, period)` to the context. Use existing UI macros (`partials/_ui.html`: icon, info, notice/badge classes); no new Tailwind build needed unless a new class is required (if so, run `tools/build-css.sh` and commit `static/tailwind.css`).

Error handling: invalid period -> 404 page. A check that raises must not break the aangifte page: the btw routes wrap the banner call so that on an unexpected exception the banner is simply omitted (log once), since the controle is advisory.

## Work breakdown (max 3 builders)
1. **Builder A, domain** (no deps). Owns: `app/domain/checks/*`, `tests/checks/*` (new dir with `conftest.py` reusing patterns from `tests/vat/conftest.py` / `tests/vat/vat_helpers.py`), `app/domain/glossary.py` additions (the 5 terms). Delivers the interface above first (types + `run_checks` skeleton) so B and C can start; then implements the checks test-first (TDD skill; money/VAT-adjacent).
2. **Builder B, controle page** (depends on A's interface). Owns: `app/web/controle_routes.py`, `app/web/templates/controle/*`, `app/main.py` (router registration only), `app/web/navigation.py` (nav item), `tests/test_controle_web.py`, `tests/test_plain_language.py` (add pages to `PAGES`), nav tests if any list `NAV_ITEMS`.
3. **Builder C, aangifte integration** (depends on A's interface and B's `controle/_banner.html`; may create the partial itself if B has not, agree via file name `app/web/templates/controle/_banner.html` owned by C). Owns: `app/web/btw_routes.py` (context only), `app/web/templates/btw/return.html`, `app/web/templates/btw/confirm.html`, `app/web/templates/controle/_banner.html`, `tests/test_btw_controle_web.py`.
Integration points: `run_checks` signature and `CheckReport` properties (`verdict`, `problem_count`, `headline`); URL `/controle/{year}/{kind}/{number}`; glossary key `controle_aangifte`.

## Test strategy
- Domain (pytest, in-memory/temp SQLite like existing vat tests): per check, a case with data in period, one just outside (day before start, day after end), empty case, and verdict combinations. Unbalanced via raw insert. Document-link exclusion. Amount sum in cents for `bank_ongeboekt`.
- Web: `/controle` redirect, page renders with and without problems (text such as "Alles lijkt in orde" and a fix link), 404 for invalid period, banner present on unfiled return and confirm pages and absent on filed return, filing still succeeds with a warning present, GET does not write.
- Plain-language: `tests/test_plain_language.py` PAGES updated; full suite (`pytest`) green.

## Risks and decisions made
- Business: "boekingen zonder document" is advisory (`let_op`), limited to manual/bank direct bookings touching a cost or revenue account. Reason: private withdrawals, bank costs and memoriaal entries legitimately lack a bon, and flagging them would train the user to ignore the list. Recommended default taken; tweak later if the user wants stricter.
- Business: nothing blocks filing (user is in control, the app is a helper). Unbooked bank transactions are `fout` in tone but still non-blocking.
- Business: inbox documents count regardless of age (an old unbooked invoice may still belong to an earlier, already-filed period; the message says "kan invloed hebben op je btw").
- Technical: no persistence of dismissed warnings; no migration. Cheap to add later.
- Technical: hrefs live in the domain as strings to keep routes thin; risk of drift if routes change, mitigated by web tests that follow the links (GET returns 200).
- Risk: bank direct bookings may carry a `source_type` set by the reconcile flow; Builder A must check `app/domain/reconcile/entries.py` and, if it sets one, include that type in the `boeking_zonder_document` filter (and exclude reconcile entries that settle a sales/purchase invoice, since those have their own document).
- Risk: the glossary test limits unused keys; every new key must be rendered via `info()` somewhere.
