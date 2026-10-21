# Backlog

Format: one feature per line. `/factory next` picks the first `[ ]` item.
Statuses: `[ ]` todo · `[~]` in progress · `[x]` completed

- [x] Project skeleton: FastAPI app, SQLite + Alembic, pytest, base layout (sidebar like MoneyMonk), `.env` config, run script (done 2026-10-21)
- [x] Core ledger: RGS-based grootboekschema seed, dagboeken, double-entry journal entries (integer cents, must balance, append-only with storno), boekjaar/periodes with locking (done 2026-10-21)
- [x] Plain-language pass: create `app/domain/glossary.py` (term → short Dutch explanation) and an info-icon/tooltip component; retrofit existing screens (sidebar, grootboek, dagboeken, journal entries, periodes) with plain-Dutch labels next to bookkeeping terms, explainers, suggested defaults and plain-Dutch error messages (see CLAUDE.md "usable without bookkeeping knowledge"); test that every term used in templates has a glossary entry (done 2026-10-21)
- [x] Relations: contacts (klanten/leveranciers) with KvK, BTW-nummer, IBAN, address; auto-match/create from extracted invoice data (done 2026-10-21)

- [x] Document inbox: manual upload of PDF/image invoices and receipts, content-addressed storage in `data/documents/`, inbox list with status (nieuw / herkend / geboekt) (done 2026-10-21)
- [ ] AI invoice extraction via Claude API: supplier details, invoice date, number, lines with amount, VAT rate/amount, suggested grootboek; confidence flags; review screen with PDF side-by-side. Use OAuth flow - so it can be used within the user's paid plan
- [ ] Purchase booking flow: approve extracted invoice → inkoopfactuur + journal entry, VAT codes, learned supplier→grootboek defaults, crediteuren
- [ ] Email intake: IMAP polling of dedicated mailbox, extract attachments (PDF/image, also nested/forwarded .eml), dedupe, feed into inbox
- [ ] Bank statement import: CAMT.053 / MT940 / CSV (ING, Rabobank, ABN AMRO, bunq), bankrekeningen, duplicate detection
- [ ] Bank reconciliation: match transactions to open invoices (IBAN, amount, invoice number in description), manual match, split/partial payments, direct-book without invoice, matching rules
- [ ] Sales invoices: create/send PDF invoices compliant with Wet OB (gapless numbering, required fields), debiteuren, credit notes, payment terms, reminders
- [ ] BTW-aangifte: quarterly/monthly report by rubriek, ICP-opgaaf, verlegd/EU handling, KOR option, export for Belastingdienst, period locking after filing
- [ ] RGS mapping: verify and fill `rgs_code` for all seeded accounts against the official RGS list (referentiegrootboekschema.nl); remove the "TODO verify" note in `app/seed/rgs_accounts.py`; migration to update existing DBs; test that every seeded code is a valid RGS code
- [ ] Reports: grootboekkaarten, proef- en saldibalans, winst-en-verliesrekening, balans, comparison vs previous year
- [ ] Fixed assets: activa with afschrijvingen, investeringsaftrek-info, automatic depreciation bookings
- [ ] Eenmanszaak year-end: privé-onttrekkingen/stortingen, winst uit onderneming overview, urenregistratie (urencriterium), IB-voorbereiding export
- [ ] Dashboard: cash position, open debiteuren/crediteuren, BTW to pay, inbox counts, quarter/year result
- [ ] Backup & export: one-click backup of DB + documents, audit-file export (XAF) and CSV exports, 7-year retention safeguards
- [ ] KvK lookup: automatically fetch company data (name, address, BTW-nummer where available) from the KvK Handelsregister API (Zoeken + Basisprofiel) when a KvK-nummer or name is entered on a relatie, and when match-or-create finds a new supplier from extracted invoice data; API key via `.env` (`KVK_API_KEY`), never committed; suggest-and-confirm (never overwrite silently); graceful offline/no-key fallback; first check feasibility (API access is paid per call and needs a KvK developer account, test environment available) and cache results
