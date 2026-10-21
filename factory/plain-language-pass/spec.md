Status: APPROVED

# Spec: Plain-language pass

## Goal and context
CLAUDE.md requires every feature to be usable without bookkeeping knowledge. The core ledger shipped with Dutch labels but raw bookkeeping jargon (Grootrekening, Debet, Credit, Dagboek, Storno, Btw-code, Memoriaal, RGS, Activa, Vergrendel...) and a few technical error messages. This pass (1) adds the central glossary `app/domain/glossary.py`, (2) adds one reusable info-icon/tooltip component, (3) retrofits sidebar, grootboek, dagboeken, boeken (list/detail/new), boekjaren/periodes with plain-Dutch-first labels, explainers, suggested defaults and plain-Dutch errors, and (4) adds tests that enforce it, so later features cannot regress.

Existing state (verified): Jinja2 templates in `app/web/templates/` (`base.html`, `partials/sidebar.html`, `ledger/*.html`), routes in `app/web/ledger_routes.py` (no logic besides parsing; owns `ACCOUNT_TYPES` / `JOURNAL_TYPES` label lists), nav in `app/web/navigation.py`, `templates` env + `page_context` in `app/web/__init__.py`, CSS in `app/web/static/app.css`, domain errors with stable `code` + Dutch `message` raised in `app/domain/ledger/service.py`, `entries.py`, `app/domain/money.py`. No JS framework besides vendored htmx.

## Non-goals
- No new bookkeeping features, no data model or migration changes, no route/URL changes, no changes to stable error `code`s.
- No i18n framework, no user-editable glossary, no onboarding wizard or help pages. No JS-driven auto-defaults (e.g. picking a BTW code when an account is chosen); defaults are server-rendered.
- Placeholder pages (Inbox, Bank, ...) get no new content.
- Seeded account names and RGS data are not renamed (that is the "RGS mapping" backlog item).

## User stories
- As a non-accountant I see "Wat heb je uitgegeven of ontvangen?"-style plain labels first and the bookkeeping term next to it, and I can hover/focus/tap an info icon to learn what it means.
- As the user I rarely pick from lists blindly: forms preselect a sensible dagboek, date, boekjaar, account code and BTW option.
- As the user, when something is wrong, the message says what is wrong and what to do.
- As the developer, I add a new term once in the glossary and a test fails if a screen uses a term without an explainer.

## Acceptance criteria

### A. Glossary (`app/domain/glossary.py`, pure Python, no web imports)
1. `@dataclass(frozen=True) class Term: key: str; term: str; plain: str; explanation: str; detect: tuple[str, ...] = ()`. `key` is a lowercase ascii slug (`[a-z_]+`); `term` is the bookkeeping term as displayed (e.g. "Grootboek"); `plain` is a short plain-Dutch phrase (e.g. "Overzicht van al je rekeningen"); `explanation` is 1-2 sentences, max 220 chars, plain Dutch, no unexplained jargon; `detect` is a tuple of regexes (case-insensitive, matched on visible text) that signal the term appears on a screen. Default detect (when empty) is `\b{term}\b`.
2. `GLOSSARY: dict[str, Term]`, plus `get_term(key) -> Term` (raises `KeyError` with a Dutch-free developer message naming the key) and `all_terms() -> list[Term]`.
3. Required keys (at minimum, each with non-empty term/plain/explanation): `grootboek`, `grootrekening`, `dagboek`, `memoriaal`, `verkoopdagboek`, `inkoopdagboek`, `bankdagboek`, `kasdagboek`, `boeking`, `boekstuk`, `debet`, `credit`, `storno`, `boekjaar`, `periode`, `vergrendelen`, `afsluiten`, `btw`, `btw_code`, `rgs`, `activa`, `passiva`, `eigen_vermogen`, `opbrengsten`, `kosten`, `systeemrekening`, `debiteuren`, `crediteuren`, `balans_evenwicht` (debet = credit), `referentie`, `inbox`, `relaties`, `rapportages`, `bank`, `kas`.
4. Domain tests (`tests/domain/test_glossary.py`): every entry has all fields filled; keys are unique slugs; explanation length <= 220; `plain` differs from `term`; `get_term` of unknown key raises `KeyError`; every `detect` regex compiles.

### B. Info component
5. Macros in `app/web/templates/partials/_info.html`, usable from any template via `{% from "partials/_info.html" import info, term_label with context %}`:
   - `info(key)`: renders `<span class="info" data-term="{{key}}"><button type="button" class="info-btn" aria-label="Uitleg: {{term}}" aria-describedby="info-{{key}}-{{n}}">i</button><span role="tooltip" id="info-{{key}}-{{n}}" class="info-tip">{{explanation}}</span></span>`. `n` is a per-render counter so ids are unique even when a key is used several times on a page.
   - `term_label(key, plain=None)`: renders `<plain-text> (<Term>)` followed by `info(key)`, i.e. plain Dutch first, bookkeeping term second, never the term alone. `plain` defaults to the glossary `plain` short text; callers may override with a context-specific phrase (e.g. "Wat is het bedrag aan de debetkant?" is not required; keep phrases short).
6. Tooltip works without JS: CSS shows `.info-tip` on `:hover` and `:focus-within` of `.info`, and on touch via focus (button is focusable). Tooltip is keyboard accessible, readable in light and dark theme (uses existing CSS variables), max-width ~ 20rem, does not overflow the viewport at 360px width (positioned inside the content area, wraps text). Unknown key raises at render time (Jinja `UndefinedError`/`KeyError`), so typos fail loudly in tests.
7. `app/web/__init__.py` registers the Jinja global `explain(key)` (returns `Term`) used by the macros, and exposes nothing else. Inside tables the icon must not break column layout (inline, no wrapping of header).

### C. Sidebar
8. `NavItem` gains optional `term_key: str | None = None` (glossary key). Items with a bookkeeping flavour get one: Boeken->`boeken`-style key is not needed; use: Inbox->`inbox`, Boeken->`boeking`, Bank->`bank`, Relaties->`relaties`, BTW->`btw`, Rapportages->`rapportages`, Instellingen->none. Verkoop/Inkoop/Activa get `debiteuren` / `crediteuren` / `activa` respectively. Labels (`Inbox`, `Boeken`, ...) are unchanged (existing tests rely on them).
9. Sidebar renders, under each label with a `term_key`, a small muted line with the glossary `plain` text and sets `title` to the explanation (plain attribute tooltip is used instead of the icon in the dark sidebar; the explanation is also in the page via `aria-label` / `title`). Contrast of the muted line >= 4.5:1 on the sidebar background in both themes.

### D. Screens (plain Dutch first, term second, explainer on every term)
Every page below must show, via `term_label`/`info`, an info icon for each glossary term that occurs in its visible text (outside data-row cells and `<option>` text; see test 28). Required content per screen:

10. **Boeken list** (`/boeken`): page lead sentence "Alle boekingen: elke euro die binnenkomt of uitgaat, vastgelegd met datum en omschrijving." Column headers keep existing words but gain plain wording: "Boekstuk" with info; "Dagboek" with info; filter label "Toon alleen dagboek" with info; badges "Storno van X" and "Gestorneerd" get info (storno) and text unchanged. Empty state: "Je hebt nog geen boekingen. Maak je eerste boeking met 'Nieuwe boeking'." Button text "Nieuwe boeking" unchanged.
11. **Boeking detail** (`/boeken/{id}`): "Dagboek", "Totaal", "Storno van", "Gestorneerd door", "Referentie" labelled with info icons; table headers: "Rekening (grootrekening)", "Debet (ontvangen/ links)", ... exact wording is the builder's but must be `term_label` for `grootrekening`, `debet`, `credit`, `btw_code`; helper text under the storno form: "Een boeking kun je niet wijzigen of verwijderen. Met een stornoboeking maak je hem ongedaan: er komt een tegengestelde boeking bij. Laat de datum leeg om dezelfde datum te gebruiken." The submit button text "Stornoboeking maken" is unchanged; the date label reads "Datum van de stornoboeking (leeg = zelfde datum)". Error alert text comes from the domain (see F).
12. **Nieuwe boeking** (`/boeken/nieuw`):
    - Intro: "Met een handmatige boeking leg je zelf vast wat er gebeurd is. Elke boeking heeft twee kanten die even groot moeten zijn: debet en credit." (info for `debet`, `credit`, `balans_evenwicht`).
    - Labels: "In welk dagboek? (Dagboek)", "Datum", "Waar gaat het over? (Omschrijving)", "Referentie (bijv. factuurnummer)", line headers via `term_label`: "Rekening (grootrekening)", "Debet", "Credit", "Btw-code", "Toelichting".
    - Suggested defaults: dagboek preselected to the memoriaal journal (code `MEM`; if inactive/missing: none) because this form is for manual bookings; date = today (as now) ; both starting lines present; BTW select first option reads "Geen btw" (value empty) instead of "-"; BTW option text is "{plain name} ({code})" using the vat code `name`, not `NL_21 ...` code-first. Account select options are grouped with `<optgroup>` per account type using plain group labels ("Wat je bezit (Activa)", "Wat je schuldig bent (Passiva)", "Eigen vermogen", "Opbrengsten (wat je verdient)", "Kosten (wat je uitgeeft)"), option text "{code} {name}".
    - Running totals: footer rows labelled "Totaal debet / credit" and "Verschil" are shown only after a failed submit (as now). When the difference is non-zero the footer shows plain text: "Er ontbreekt {bedrag} aan de {debet|credit}kant." 
    - Per-line validation messages (route-level, Dutch): "Regel {n}: kies een rekening.", "Regel {n}: vul een bedrag in bij debet of credit, niet allebei." (see F for messages produced by the domain).
    - Missing dagboek: "Kies in welk dagboek je wilt boeken." ; invalid date: "Vul een geldige datum in, bijvoorbeeld 31-12-2026."
13. **Grootboek** (`/instellingen/grootboek`): `<h2>` "Grootboek" with `term_label("grootboek")` and lead sentence "Dit is de lijst met alle rekeningen waarop je boekingen worden vastgelegd, zoals Bank, Omzet en Kantoorkosten." Add-form labels: "Rekeningnummer (4 cijfers)", "Naam", "Soort rekening" with `term_label("grootrekening")`; the soort select options use the plain group labels of item 12 (single source of these labels: `ACCOUNT_TYPE_LABELS` defined once in the domain, see F-bis). Table headers: "Code", "Naam", "RGS" (info `rgs`), "Status"; badge "Systeem" has info (`systeemrekening`: "Standaardrekening die het programma zelf nodig heeft; je kunt hem niet hernoemen of verwijderen."). Group headings (`<h3>`) use the plain group label with info for activa/passiva/eigen_vermogen/opbrengsten/kosten. Buttons "Deactiveren"/"Activeren" get a `title` explaining "Verbergt de rekening bij nieuwe boekingen; bestaande boekingen blijven staan."
    - Suggested default: the new-account form prefills a free rekeningnummer for the default type (expense): `suggest_account_code(session, type)` (see F-bis) -> shown in the code field as value and described by helper text "Voorstel: eerste vrije nummer in dit gebied. Pas aan als je wilt."
14. **Dagboeken** (`/instellingen/dagboeken`): lead sentence "Een dagboek is een map waarin boekingen van dezelfde soort bij elkaar staan, bijvoorbeeld alle bankmutaties." with `term_label("dagboek")`. Type select options show plain names with term: "Verkoop (verkoopfacturen)", "Inkoop (inkoopfacturen)", "Bank (bankrekening)", "Kas (contant geld)", "Memoriaal (overige boekingen)"; table column Type shows the same label (not the raw `verkoop` code) and the `memoriaal` type has an info icon. "Grootrekening (bank/kas)" label becomes "Bij welke rekening hoort dit dagboek? (alleen bij bank en kas)" with info; when exactly one active asset account whose name contains "Bank" exists, it is preselected for type bank (and "Kas" for kas) via server-side default of the initial values; the option "-" reads "Geen". Default type remains `bank`.
15. **Boekjaren / periodes** (`/instellingen/boekjaren`): lead sentence "Een boekjaar is het jaar waarover je je administratie bijhoudt (meestal een kalenderjaar). Het is verdeeld in 12 periodes (maanden)." with info for `boekjaar`, `periode`. Create form: label "Welk jaar?" with default = the first year that does not yet exist starting from the current year (current year if none exist), computed in the domain (`suggest_fiscal_year`, F-bis). Statuses: "Open" with title "Je kunt hierin nog boeken", "Vergrendeld" with title "Hierin kan niet meer worden geboekt". Button "Vergrendel periode" -> text "Periode vergrendelen" with info (`vergrendelen`); "Boekjaar afsluiten" keeps text and gets info (`afsluiten`). Confirm dialogs (`hx-confirm`) in plain Dutch: "Periode {n} van {jaar} vergrendelen? Daarna kun je er niets meer in boeken, wijzigen of storneren. Dit kun je niet ongedaan maken." and "Boekjaar {jaar} afsluiten? Alle 12 periodes worden vergrendeld; daarna kun je in dit jaar niet meer boeken. Dit kun je niet ongedaan maken." Empty state keeps the sentence "Er is nog geen boekjaar. Maak eerst een boekjaar aan om te kunnen boeken."
16. **Settings sub-nav** (`_settings_nav.html`): links keep names Grootboek/Dagboeken/Boekjaren and gain `title` attributes with the glossary `plain` text.
17. Headings never use a bookkeeping term alone: `<h1>`/`<h2>` that is a bare term (Grootboek, Dagboeken, Boekjaren) is followed by the lead sentence (items 13-15), and `term_label` is used on the heading where it is the primary introduction of the term.

### E. Plain-Dutch errors
18. All user-visible messages from `app/domain/ledger/service.py`, `entries.py`, `periods.py` and `money.py` say what is wrong and what to do; no raw codes, ids or English. Exact required messages (tests assert these substrings):
    - `UNBALANCED`: `"Debet en credit zijn niet gelijk: er ontbreekt {euro} aan de {debet|credit}kant. Pas een bedrag aan of voeg een regel toe."` where `{euro}` = `format_euro(abs(diff))` and the side is the smaller one (debit < credit -> "debet"). Also shows totals: `"(debet {x}, credit {y})"` after the first sentence.
    - `TOO_FEW_LINES`: `"Een boeking heeft minimaal twee regels nodig: één voor debet en één voor credit."`
    - `INVALID_LINE_AMOUNT`: `"Regel {n}: vul bij debet óf bij credit een bedrag groter dan nul in, niet allebei en niet leeg."`
    - `ACCOUNT_NOT_FOUND` (account id): `"Deze rekening bestaat niet meer. Kies een andere rekening."` (no id in the text).
    - `ACCOUNT_NOT_POSTABLE`: `"Op rekening {code} {name} kun je niet boeken, want het is een kopregel. Kies een rekening eronder."`
    - `ACCOUNT_INACTIVE`: `"Rekening {code} {name} is uitgezet. Kies een andere rekening of zet deze rekening weer aan onder Instellingen > Grootboek."`
    - `INVALID_VAT_CODE`: `"Deze btw-code is onbekend of niet meer in gebruik. Kies een andere uit de lijst."`
    - `NO_OPEN_PERIOD`: `"Er is geen boekjaar voor {dd-mm-jjjj}. Maak eerst het boekjaar aan onder Instellingen > Boekjaren."`
    - `PERIOD_LOCKED`: `"De periode van {dd-mm-jjjj} is vergrendeld, dus je kunt er niet meer in boeken. Kies een datum in een open periode."`
    - `ALREADY_REVERSED`: `"Boeking {nr} is al ongedaan gemaakt met stornoboeking {nr2}."`
    - `CANNOT_REVERSE_STORNO`: `"Een stornoboeking kun je niet nog eens ongedaan maken. Maak in plaats daarvan een nieuwe boeking."`
    - `YEAR_EXISTS`: `"Boekjaar {jaar} bestaat al. Kies een ander jaar."`; `YEAR_NOT_FOUND`: `"Boekjaar {jaar} bestaat niet. Maak het eerst aan onder Instellingen > Boekjaren."`
    - `ACCOUNT_IN_USE`: `"Rekening {code} wordt al gebruikt in boekingen en kan niet worden verwijderd. Zet de rekening uit; dan verschijnt hij niet meer bij nieuwe boekingen."`
    - `INVALID_ACCOUNT` code length: `"Een rekeningnummer bestaat uit precies 4 cijfers, bijvoorbeeld 4010."`; name: `"Geef de rekening een naam."`; type: `"Kies een soort rekening uit de lijst."`
    - `DUPLICATE_CODE`: `"Rekeningnummer {code} bestaat al. Kies een ander nummer."` / `"Dagboekcode {code} bestaat al. Kies een andere code."`
    - `SYSTEM_ACCOUNT`: `"Dit is een standaardrekening die het programma zelf nodig heeft; je kunt hem niet wijzigen of verwijderen."`
    - `INVALID_JOURNAL`: code: `"Een dagboekcode bestaat uit 1 tot 6 hoofdletters of cijfers, bijvoorbeeld BANK1."`; name: `"Geef het dagboek een naam."`; type: `"Kies een soort dagboek uit de lijst."`; bank/kas without account: `"Bij een bank- of kasdagboek hoort een rekening. Kies de rekening van je bank of kas."`
    - `JOURNAL_NOT_FOUND`/`JOURNAL_INACTIVE`/`ENTRY_NOT_FOUND`/`PERIOD_NOT_FOUND`/`INVALID_ENTRY`: plain Dutch with a next step ("Kies een ander dagboek.", "Ga terug naar Boeken en kies de boeking opnieuw."); opening-entry: `"Een beginbalans-boeking kan alleen in het memoriaal (overige boekingen) worden gemaakt."`
    - `InvalidAmountError` (money): `"'{tekst}' is geen geldig bedrag. Schrijf bijvoorbeeld 1.234,56 of 12,50 (maximaal twee cijfers achter de komma)."`
    - `InvalidDescriptionError`: `"Vul een omschrijving in, bijvoorbeeld 'Kantoorbenodigdheden'."` and `"De omschrijving is te lang (maximaal 255 tekens)."`; `InvalidDateError`: `"Vul een geldige datum in, bijvoorbeeld 31-12-2026."`
    Developer-facing `TypeError`s (money type guards) stay as is. Error `code` attributes and exception classes are unchanged.
19. Route-level messages in `ledger_routes.py` (invalid date, missing dagboek/rekening, per-line parse errors) follow the same style (item 12). The shared error include `_error.html` keeps `role="alert"`; error text that exists in a page is the domain `message` verbatim (no wrapping like "Fout:").
20. Existing assertions that checked old wording are updated in the same change: `tests/domain/test_entries.py:53` and `tests/test_ledger_web.py:93` (`"evenwicht"` -> `"Debet en credit zijn niet gelijk"`), plus any other that fails because of reworded messages. Strings `Scheef`, `Regel 1`, `boekjaar`, `vergrendeld`, `Stornoboeking maken`, `Storno van`, `Gestorneerd door`, `Regel toevoegen`, `Eigen rekening` remain valid.

### F-bis. Domain helpers (suggested defaults)
21. In `app/domain/ledger/` (exported from `app.domain.ledger`):
    - `ACCOUNT_TYPE_LABELS: dict[str, str]` (asset/liability/equity/revenue/expense -> plain labels from item 12) and `JOURNAL_TYPE_LABELS: dict[str, str]` (item 14). `ledger_routes.py` builds its tuple lists from these (single source) and drops its own hard-coded labels.
    - `suggest_account_code(session, type) -> str`: returns a 4-digit string that is not an existing account code. Do not hard-code ranges: derive min/max seeded code per type from the accounts in the DB (seeded from `app/seed/rgs_accounts.py`). Algorithm: highest existing code of that type + 10, rounded down to a multiple of 10; if that is > 9999 or collides, fall back to the first unused code above the type's minimum. Deterministic; tested with a small seeded DB.
    - `suggest_fiscal_year(session, today: date) -> int`: smallest year >= `today.year` without a boekjaar.
    - `default_journal_id(session, journal_type) -> int | None`: id of the first active journal of that type (used for memoriaal preselect), None if none.
22. Unit tests for the three helpers (item 21) incl. edge cases: no years; current year exists; consecutive years exist; account range full.

### G. Enforcement tests
23. `tests/test_plain_language.py` (web, uses the existing `client` fixtures, seeded DB with a boekjaar and at least one entry and one storno) fetches every ledger page: `/boeken`, `/boeken/nieuw`, one entry detail, one storno detail, `/instellingen/grootboek`, `/instellingen/dagboeken`, `/instellingen/boekjaren`, plus `/` after redirect and one placeholder page (sidebar) and asserts:
    a. Template key check (static): regex over all `app/web/templates/**/*.html` for `info("key")`, `term_label("key"...)`, and `explain("key")` and sidebar `term_key` values in `navigation.py`; every key exists in `GLOSSARY`. The reverse is also tested: every glossary key is used by at least one template, nav item or label table (so dead entries are noticed) -- exception list `UNUSED_OK` in the test is allowed, max 5 keys, each commented.
    b. Rendered check: for each page, strip `<script>`, `<style>`, `<td>…</td>` cells, `<option>` and tooltip text; for each `Term` whose `detect` regex matches the remaining visible text (including `<th>`, labels, buttons, headings, paragraphs, badges), the page must contain `data-term="{key}"` (or, in the sidebar, the nav item `title` of that key). Failure message lists page URL + missing term keys.
    c. Plain-first check: no `<label>`, `<th>`, `<h1-3>`, `<button>` text on those pages is exactly a bare glossary `term` (case-insensitive) unless the same element also contains an `info` marker or a parenthesised plain phrase. Exceptions enumerated in the test (e.g. "Boeken" nav label, "Bank").
    d. Error check: submitting an unbalanced entry (debet 100,00 / credit 87,90) returns 422 with `role="alert"` and text containing "Debet en credit zijn niet gelijk: er ontbreekt € 12,10" ; an invalid date shows "Vul een geldige datum in"; posting into a locked period shows "is vergrendeld" and "Kies een datum in een open periode"; duplicate account code shows "bestaat al. Kies een ander nummer."
    e. Message lint (domain level, `tests/domain/test_error_messages.py`): grep `service.py`, `entries.py`, `periods.py`, `money.py` for all `_error(...)`/`*Error(...)` message literals via `ast`; assert none contains an ALL_CAPS code token (`[A-Z]{2,}_[A-Z_]+`) or the words `exception`, `traceback`, `None`, `invalid` (case-insensitive), and each message ends with `.` or `?`.
24. Tooltip component test: render `info("debet")` through the Jinja env: output contains `data-term="debet"`, role `tooltip`, the explanation text, `aria-describedby` equals the tooltip id; two uses of the same key on one page yield different ids; unknown key raises.
25. Defaults tests (web): `/boeken/nieuw` has the MEM dagboek `selected`; BTW select first option text is "Geen btw"; `/instellingen/grootboek` code input has a prefilled 4-digit value that is not an existing code; `/instellingen/boekjaren` year input equals `suggest_fiscal_year`; dagboeken table shows "Memoriaal (overige boekingen)" and not the raw word `memoriaal` as plain cell text.
26. Existing test suite stays green (`pytest -q`), with only the assertion updates in item 20.
27. Glossary quality gate (in `tests/domain/test_glossary.py`): an `explanation` must not contain the bookkeeping `term` of a different entry from {debet, credit, grootrekening, dagboek, storno, periode} (word match, case-insensitive) unless that entry's own key is `debet`/`credit` pair (they may reference each other). Reword explanations in everyday words instead of relaxing the test.
28. Test helper `visible_text(html)` and `strip_cells(html)` live in `tests/web_helpers.py` (owned by part C) so later features reuse the same enforcement (`assert_plain_language(client, url)` helper; later features' specs should add their pages to the list in `tests/test_plain_language.py`). Add one sentence to CLAUDE.md is NOT part of this task.

## Technical approach
- Glossary is a module-level dict built from a list of `Term`s; no DB, no IO. Web layer imports it; domain error modules do not need it (messages are literal strings).
- Component = Jinja macros + CSS only. `explain` is a Jinja global (`templates.env.globals["explain"] = get_term`). Counter for unique ids: a `namespace` stored on the macro call via `caller`-free approach: use a module-level `itertools.count()` exposed as global `next_info_id()`, thread-safe enough for single-user local use (ids only need uniqueness within a response).
- Sidebar: `NavItem.term_key` + `MarkedNavItem` copies it; template reads `explain(item.term_key)`.
- Plain labels for account/journal types live in the domain (F-bis) so routes and templates share one source; templates never contain duplicated glossary text.
- Error rewording is edit-in-place of message strings only; control flow and codes untouched. Route-level validation strings stay in `ledger_routes.py` (they are presentation of form input errors, not domain rules).
- Defaults are computed server-side in domain helpers and passed through `ledger_routes.py` as initial `values`; no JS.
- CSS: `.info`, `.info-btn` (1.1rem round button, border, `aria-label`), `.info-tip` (absolutely positioned, hidden by default, `max-width: min(20rem, 90vw)`), `.hint` (muted helper text), `.nav-sub` (sidebar sub-line), `.lead` (intro paragraph); all colours via existing `:root` variables with dark-mode overrides.

## Work breakdown (disjoint file ownership)
**Part A: glossary, component, sidebar, CSS** (no deps; build first or in parallel using the API in items 1-9)
- Owns: `app/domain/glossary.py`, `app/web/templates/partials/_info.html`, `app/web/templates/partials/sidebar.html`, `app/web/navigation.py`, `app/web/__init__.py`, `app/web/static/app.css`, `app/web/templates/base.html` (only if needed), `tests/domain/test_glossary.py`, `tests/test_info_component.py` (items 4, 24, 27 and sidebar assertions of 8-9).
- Integration points: macro names/signatures `info(key)`, `term_label(key, plain=None)`, global `explain(key)`, CSS classes `.hint`, `.lead`. Glossary must contain all keys of item 3 on first commit (part C needs them); extra keys may be added by C only by asking A (A owns the file).

**Part B: domain messages and helpers** (no deps)
- Owns: `app/domain/ledger/service.py`, `app/domain/ledger/entries.py`, `app/domain/ledger/periods.py`, `app/domain/ledger/__init__.py`, `app/domain/errors.py`, `app/domain/money.py`, `tests/domain/*` except `test_glossary.py`, `tests/ledger/*`, new `tests/domain/test_error_messages.py` and `tests/domain/test_suggestions.py`.
- Delivers items 18, 20 (domain-side assertions), 21, 22, 23e. Exports `ACCOUNT_TYPE_LABELS`, `JOURNAL_TYPE_LABELS`, `suggest_account_code`, `suggest_fiscal_year`, `default_journal_id` from `app.domain.ledger`.

**Part C: screens and web tests** (depends on A's macro/glossary API and B's helper signatures; may start with stubs of those names and rebase)
- Owns: `app/web/ledger_routes.py`, `app/web/templates/ledger/*.html`, `app/web/templates/404.html`, `app/web/templates/placeholder.html`, `tests/test_ledger_web.py`, new `tests/test_plain_language.py`, `tests/web_helpers.py`.
- Delivers items 10-17, 19, 20 (web-side assertion), 23a-d, 25, 28.
- Integration order: A and B merge first (disjoint), then C is rebased and run against both; the final run is `pytest -q` on the combined branch.

## Test strategy
Test-first for A (glossary invariants) and B (message strings, helpers, money-related messages use `format_euro`); C writes `test_plain_language.py` first (it fails until screens are retrofitted, which is the intended red state). Rendered-HTML tests use the existing FastAPI TestClient fixtures from `tests/conftest.py`; no browser is needed. Manual check by reviewer: open each screen at 360px and 1280px, hover/tab to an info icon, check dark mode.

## Risks and decisions made
- **Terms in data cells excluded from detection** (seeded account names such as "Debiteuren", "Bank", "BTW af te dragen" would otherwise demand an icon in every row). Decision: the grootboek page instead carries the `debiteuren`/`crediteuren` explainer in its lead sentence area only if the builder wants; not required.
- **Tooltip via CSS hover/focus, not JS**: no dependency, works with hx-boost; trade-off: on touch devices the first tap focuses the button, which shows the tip. Accepted.
- **Glossary in Python, not YAML/DB**: matches CLAUDE.md (`app/domain/glossary.py`) and gets import-time validation by tests.
- **Sidebar uses `title` + sub-line, not the icon**: icon tooltips clip inside the fixed, scrollable dark sidebar; the sub-line gives the plain label always visible.
- **Account code suggestion derived from the seed ranges** rather than hard-coded; if the seed layout is unconventional the helper still returns an unused 4-digit code.
- **Labels for account types change** ("Activa" -> "Wat je bezit (Activa)") – any test asserting the old exact option text must be updated by part C.
- **No business questions**: scope, wording and defaults were decidable from CLAUDE.md. Dutch wording is a first proposal; reviewers may suggest tweaks without changing structure.
