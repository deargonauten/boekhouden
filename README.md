# Boekhouden

Lokale boekhoudsoftware voor een Nederlandse eenmanszaak of VOF, voor één gebruiker. Het draait op je eigen computer (geen cloud, geen Docker) en volgt een eenvoudige flow: **inbox → nakijken → boeken → rapportage**. Gebouwd voor mensen zonder boekhoudkennis: de schermen gebruiken gewoon Nederlands en leggen elk vakterm uit.

> **Let op:** dit is een hobbyproject, geen goedgekeurd boekhoudpakket. Controleer je btw-aangifte en jaarcijfers altijd zelf of laat ze controleren door een boekhouder. Er is geen garantie op juistheid.

## Wat kan het?

- **Inbox:** facturen en bonnen uploaden of laten binnenkomen via een eigen mailbox (IMAP).
- **Uitlezen met Claude:** pdf's en foto's worden omgezet naar factuurgegevens; jij kijkt ze na voordat er iets geboekt wordt. Ook facturen uit andere landen en in andere valuta (met wisselkoers en verlegde btw).
- **Boeken:** dubbel boekhouden op een RGS-grootboekschema, bedragen in hele centen, boekingen kunnen alleen gecorrigeerd worden met een stornoboeking.
- **Bank:** import van MT940, CAMT.053 en csv (ING, Rabobank, bunq) en afletteren met facturen.
- **Verkoopfacturen** met doorlopende nummering, pdf en betalingsherinneringen.
- **Btw-aangifte** per periode (rubrieken 1a t/m 5b), controle vooraf en export.
- **Beginbalans, relaties** (klanten en leveranciers) en bedrijfsgegevens.

## Wat heb je nodig?

- Python 3.12 of nieuwer
- [uv](https://docs.astral.sh/uv/) (pakketbeheer)
- Voor het uitlezen van facturen, één van beide:
  - de [Claude Code CLI](https://claude.com/claude-code), ingelogd met `claude auth login` (gaat via je abonnement), of
  - een Anthropic API-sleutel (betaalt per gebruik)

Zonder een van die twee werkt alles behalve het automatisch uitlezen; je kunt gegevens dan zelf invullen.

## Snel starten

```sh
git clone git@github.com:deargonauten/boekhouden.git
cd boekhouden
./boekhouden
```

Dit installeert de afhankelijkheden, maakt `.env` aan uit `.env.example`, voert de databasemigraties uit en start de app op <http://127.0.0.1:8000>.

Andere commando's:

```sh
./boekhouden update    # git pull, afhankelijkheden bijwerken, migreren
./boekhouden migrate   # alleen migraties uitvoeren
./boekhouden test      # tests draaien
./boekhouden health    # /health van de draaiende app opvragen
./boekhouden help
```

Handmatig kan ook: `uv sync`, `cp .env.example .env`, `./run.sh`.

Open de app en begin met **Instellingen**: vul je bedrijfsgegevens in, kies een boekjaar en (optioneel) voer je beginbalans in.

## Instellingen (`.env`)

Alles staat uitgelegd in `.env.example`. De belangrijkste:

| Variabele | Doel |
| --- | --- |
| `DATABASE_PATH`, `DOCUMENTS_DIR` | waar database en documenten staan (standaard onder `data/`) |
| `APP_HOST`, `APP_PORT`, `APP_RELOAD` | webserver; standaard alleen bereikbaar op je eigen computer |
| `EXTRACTION_BACKEND` | `auto`, `claude_cli` of `anthropic_api` |
| `ANTHROPIC_API_KEY` | alleen nodig voor de API-variant |
| `IMAP_*` | optioneel: een eigen mailbox waaruit facturen worden opgehaald |

### Factuurmailbox (optioneel)

Gebruik een **apart mailadres** voor facturen en stuur ze daar naartoe door. Heeft je provider app-wachtwoorden (Gmail, Microsoft, iCloud), maak er dan een aan in plaats van je gewone wachtwoord. De app leest alleen de map `IMAP_FOLDER`, verplaatst verwerkte mail naar een andere map en verwijdert niets.

## Je gegevens

Alles wat van jou is staat in `data/` (de SQLite-database en de opgeslagen facturen) en in `.env` (sleutels en wachtwoorden). Beide staan in `.gitignore` en horen **nooit** in git, zeker niet nu de repository publiek is.

- **Maak back-ups van `data/`.** Je moet je administratie 7 jaar bewaren.
- Geboekte documenten worden niet verwijderd; alleen een nog niet geboekt inboxdocument kan weg.
- De app heeft geen inlog en is bedoeld voor `127.0.0.1`. Zet hem niet zomaar open op een netwerk of het internet.
- Facturen die je laat uitlezen worden naar Claude (Anthropic) gestuurd. Doe dat niet met documenten die je daar niet wilt hebben.

## Ontwikkelen

```sh
uv run pytest                       # alle tests (tijdelijke database, raakt data/ niet aan)
uv run alembic revision -m "..."    # nieuwe migratie
uv run alembic upgrade head
uv run alembic check
./tools/build-css.sh                # Tailwind/daisyUI opnieuw bouwen (standalone CLI, geen Node)
```

Indeling:

```
app/domain/    bedrijfslogica (geen FastAPI/HTTP)
app/web/       routes, Jinja2-templates en HTMX, statische bestanden
app/models/    SQLAlchemy-modellen
app/seed/      standaard grootboek, btw-codes en dagboeken
migrations/    Alembic
tests/         pytest
```

Uitgangspunten en regels (bedragen in centen, sluitende boekingen, glossary voor vaktermen, enzovoort) staan in [`CLAUDE.md`](CLAUDE.md).

## Licentie

Nog niet gekozen. Zonder licentie mag niemand de code hergebruiken; voeg een `LICENSE` toe als je dat wel wilt toestaan.
