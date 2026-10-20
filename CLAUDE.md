# Boekhouden

Local, single-user Dutch bookkeeping software for an eenmanszaak/VOF. Inspired by MoneyMonk (simple inbox → boeken → rapportage flow).

## Decisions
- Stack: Python 3.12, FastAPI, SQLite (single file, `data/boekhouden.db`), Jinja2 + HTMX UI on localhost. No Docker.
- Migrations: Alembic. Tests: pytest.
- Invoice extraction: Claude API (PDF/image → structured JSON). API key via `.env` (`ANTHROPIC_API_KEY`), never committed.
- Email intake: IMAP polling of a dedicated mailbox; attachments stored under `data/documents/` (content-addressed, never deleted).
- Entity: eenmanszaak/VOF (IB, urencriterium, KOR optional). No BV features.

## Domain rules (Dutch compliance)
- Money is stored as integer cents, never floats. VAT rates: 21%, 9%, 0%, verlegd, EU/export.
- Double-entry bookkeeping on a RGS-based grootboekschema (referentiegrootboekschema). Every journal entry must balance.
- Bookings are append-only: corrections via storno/correctieboeking, closed periods locked (Awr bewaarplicht 7 jaar; documents kept with the booking).
- Sequential, gapless sales invoice numbers; invoices must contain all required fields (art. 35a Wet OB).
- BTW-aangifte rubrieken (1a, 1b, 2a, 3b, 4a, 4b, 5b, ...) derived from VAT codes on lines.

## Conventions
- Dutch UI labels and domain terms (grootboek, dagboek, debiteuren, crediteuren); English code identifiers.
- Business logic in `app/domain/`, no logic in route handlers. Tests first for anything that touches money or VAT (see tdd skill).
