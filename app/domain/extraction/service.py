"""Extraction service: build the request, store the result, review it.

All functions flush but never commit; the caller owns the transaction. The
extractor call itself is NOT made here (except in `run_extraction`, meant for
tests and one-shot use): routes commit after `build_request`, call the
extractor without a write transaction open, then `store_result`/`store_failure`.

Logging never contains invoice content: document id, backend, error class.
"""

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.domain.documents import (
    DocumentStorage,
    document_path,
    get_document,
    mark_recognized,
)
from app.domain.errors import (
    FAILED_MESSAGE,
    NOT_ALLOWED_MESSAGE,
    NOT_FOUND_MESSAGE,
    ExtractionError,
    ExtractionNotAllowedError,
    ExtractionNotFoundError,
    UNAVAILABLE_MESSAGE,
)
from app.domain.extraction.review import ParsedReview, ReviewInput, parse_review
from app.domain.extraction.suggestions import (
    AccountRef,
    resolve_account_code,
    resolve_vat_code,
    resolve_vat_code_for_account,
)
from app.domain.extraction.types import (
    AccountHint,
    ExtractedInvoice,
    ExtractedLine,
    ExtractionRequest,
    InvoiceExtractor,
)
from app.domain.extraction.validation import Flag, assess, flagged_fields, merge_flags
from app.domain.relations import ExtractedContact, match_or_create_contact
from app.models import Account, Document, InvoiceExtraction, InvoiceExtractionLine, VatCode

log = logging.getLogger(__name__)

AMBIGUOUS_SUPPLIER = (
    "Er zijn meerdere leveranciers met deze naam. Kies na het nakijken zelf de juiste."
)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# --- reference data -------------------------------------------------------------------
def _account_refs(session: Session) -> list[AccountRef]:
    rows = session.scalars(select(Account).order_by(Account.code))
    return [AccountRef(a.code, a.type, bool(a.is_postable), bool(a.is_active), a.name) for a in rows]


def _vat_rates(session: Session) -> dict[str, int]:
    rows = session.scalars(select(VatCode).where(VatCode.is_active.is_(True)).order_by(VatCode.code))
    return {v.code: v.rate_bp for v in rows}


def _account_ids(session: Session) -> dict[str, int]:
    return {code: id_ for id_, code in session.execute(select(Account.id, Account.code))}


def _default_vats(session: Session) -> dict[str, str | None]:
    return {code: vat for code, vat in session.execute(select(Account.code, Account.default_vat_code))}


# --- flags (stored as JSON) -------------------------------------------------------------
def _dump(flags: list[Flag]) -> str:
    return json.dumps(
        [{"field": f.field, "level": f.level, "reason": f.reason} for f in flags],
        ensure_ascii=False,
    )


def _load(text: str | None) -> list[Flag]:
    try:
        return [Flag(d["field"], d["level"], d["reason"]) for d in json.loads(text or "[]")]
    except (ValueError, KeyError, TypeError):
        return []


def extraction_flags(extraction: InvoiceExtraction) -> list[Flag]:
    """Flags on the header fields (supplier, dates, totals, ...)."""
    return _load(extraction.flags_json)


def line_flags(line: InvoiceExtractionLine) -> list[Flag]:
    """Flags on one line; `field` is local: description|amount|vat_code|vat_amount|account."""
    return _load(line.flags_json)


def flagged_count(extraction: InvoiceExtraction) -> int:
    """Number of fields the owner should check ("N velden om te controleren")."""
    n = len(flagged_fields(extraction_flags(extraction)))
    return n + sum(len(flagged_fields(line_flags(ln))) for ln in extraction.lines)


def _split_flags(flags: list[Flag]) -> tuple[list[Flag], dict[int, list[Flag]]]:
    header: list[Flag] = []
    per_line: dict[int, list[Flag]] = {}
    for f in flags:
        parts = f.field.split(".", 2)
        if parts[0] == "line" and len(parts) == 3 and parts[1].isdigit():
            per_line.setdefault(int(parts[1]), []).append(Flag(parts[2], f.level, f.reason))
        else:
            header.append(f)
    return header, per_line


def _supplier_flags(result) -> list[Flag]:
    flags = [Flag("supplier", "medium", w) for w in result.warnings]
    if result.status == "ambiguous":
        flags.append(Flag("supplier", "medium", AMBIGUOUS_SUPPLIER))
    return flags


# --- lookups ----------------------------------------------------------------------------
def find_extraction(session: Session, document_id: int) -> InvoiceExtraction | None:
    return session.scalar(
        select(InvoiceExtraction).where(InvoiceExtraction.document_id == document_id)
    )


def get_extraction(session: Session, document_id: int) -> InvoiceExtraction:
    extraction = find_extraction(session, document_id)
    if extraction is None:
        raise ExtractionNotFoundError(NOT_FOUND_MESSAGE)
    return extraction


def _editable_document(session: Session, document_id: int) -> Document:
    document = get_document(session, document_id)
    if document.status == "geboekt":
        raise ExtractionNotAllowedError(NOT_ALLOWED_MESSAGE)
    return document


# --- request ------------------------------------------------------------------------------
def build_request(session: Session, storage: DocumentStorage, document_id: int) -> ExtractionRequest:
    """Read-only: the file bytes plus the accounts and BTW codes the model may choose from."""
    document = _editable_document(session, document_id)
    content = document_path(storage, document).read_bytes()
    accounts = tuple(
        AccountHint(a.code, a.name)
        for a in _account_refs(session)
        if a.type == "expense" and a.is_postable and a.is_active
    )
    return ExtractionRequest(
        content=content,
        content_type=document.content_type,
        filename=document.original_filename,
        accounts=accounts,
        vat_codes=tuple(_vat_rates(session)),
    )


# --- result / failure -------------------------------------------------------------------------
def _replace_lines(
    session: Session,
    extraction: InvoiceExtraction,
    rows: list[dict],
) -> None:
    """Delete + insert (working data); deletes are flushed first for the unique position."""
    session.execute(
        delete(InvoiceExtractionLine).where(InvoiceExtractionLine.extraction_id == extraction.id)
    )
    session.flush()
    for position, row in enumerate(rows):
        session.add(InvoiceExtractionLine(extraction_id=extraction.id, position=position, **row))
    session.flush()
    session.expire(extraction, ["lines"])


def _line_rows(
    lines: list[ExtractedLine],
    per_line_flags: dict[int, list[Flag]],
    accounts: list[AccountRef],
    vat_rates: dict[str, int],
    account_ids: dict[str, int],
    default_vats: dict[str, str | None] | None = None,
) -> list[dict]:
    rows = []
    for i, line in enumerate(lines):
        account_code = resolve_account_code(line.suggested_account_code, accounts)
        vat_code, _inferred = resolve_vat_code(line, vat_rates)
        if vat_code is None:  # fall back to the account's standaard btw-tarief
            vat_code = resolve_vat_code_for_account(account_code, default_vats or {}, vat_rates)
        rows.append(
            dict(
                description=line.description,
                amount_excl_cents=line.amount_excl_cents,
                vat_amount_cents=line.vat_amount_cents,
                vat_code=vat_code,
                account_id=account_ids.get(account_code) if account_code else None,
                flags_json=_dump(per_line_flags.get(i, [])),
            )
        )
    return rows


def _apply_learned_defaults(
    session: Session, extraction: InvoiceExtraction, inferred_vat_positions: set[int] | None = None
) -> None:
    """Leerfunctie: lines without a rekening get the leverancier's learned choice."""
    from app.domain.purchase.learned import apply_to_lines  # late import: purchase imports extraction

    apply_to_lines(session, extraction, inferred_vat_positions=inferred_vat_positions or set())


def store_result(
    session: Session,
    document_id: int,
    extractor_name: str,
    model: str | None,
    invoice: ExtractedInvoice,
) -> InvoiceExtraction:
    """Assess, resolve and persist an extraction; the document becomes `herkend`."""
    document = _editable_document(session, document_id)
    accounts, vat_rates = _account_refs(session), _vat_rates(session)

    flags = assess(invoice, accounts, vat_rates, date.today())
    match = match_or_create_contact(session, invoice.supplier, "supplier", create=False)
    header, per_line = _split_flags(merge_flags([*flags, *_supplier_flags(match)]))

    now = _now()
    extraction = find_extraction(session, document_id)
    if extraction is None:
        extraction = InvoiceExtraction(document_id=document_id, created_at=now)
        session.add(extraction)
    sup = invoice.supplier
    extraction.status = "ok"
    extraction.extractor = extractor_name
    extraction.model = model
    extraction.error_code = None
    extraction.error_message = None
    extraction.raw_json = invoice.raw
    extraction.kind = invoice.kind
    extraction.supplier_name = sup.name
    extraction.supplier_kvk = sup.kvk
    extraction.supplier_btw_number = sup.btw_number
    extraction.supplier_iban = sup.iban
    extraction.supplier_address_line = sup.address_line
    extraction.supplier_postal_code = sup.postal_code
    extraction.supplier_city = sup.city
    extraction.supplier_country = sup.country
    extraction.contact_id = match.contact.id if match.contact is not None else None
    extraction.invoice_number = invoice.invoice_number
    extraction.invoice_date = invoice.invoice_date
    extraction.due_date = invoice.due_date
    extraction.currency = (invoice.currency or "EUR").upper()
    extraction.total_excl_cents = invoice.total_excl_cents
    extraction.total_vat_cents = invoice.total_vat_cents
    extraction.total_incl_cents = invoice.total_incl_cents
    extraction.flags_json = _dump(header)
    extraction.notes = " ".join(invoice.notes) or None
    extraction.reviewed_at = None
    extraction.updated_at = now
    session.flush()

    _replace_lines(
        session,
        extraction,
        _line_rows(
            list(invoice.lines),
            per_line,
            accounts,
            vat_rates,
            _account_ids(session),
            _default_vats(session),
        ),
    )
    _apply_learned_defaults(
        session,
        extraction,
        inferred_vat_positions={i for i, ln in enumerate(invoice.lines) if resolve_vat_code(ln, vat_rates)[1]},
    )
    if document.status == "nieuw":
        mark_recognized(session, document_id)
    log.info(
        "extraction stored document=%s extractor=%s flags=%s",
        document_id,
        extractor_name,
        flagged_count(extraction),
    )
    return extraction


def store_failure(
    session: Session,
    document_id: int,
    extractor_name: str,
    error: Exception,
    model: str | None = None,
) -> InvoiceExtraction:
    """Remember a failed attempt (document stays `nieuw`); a good earlier result is kept."""
    _editable_document(session, document_id)
    if isinstance(error, ExtractionError):
        code, message = error.code, error.message
        log.info("extraction failed document=%s extractor=%s error=%s", document_id, extractor_name, type(error).__name__)
    else:
        code, message = "EXTRACTION_FAILED", FAILED_MESSAGE
        log.warning(
            "extraction failed document=%s extractor=%s error=%s",
            document_id,
            extractor_name,
            type(error).__name__,
            exc_info=error,
        )
    now = _now()
    extraction = find_extraction(session, document_id)
    if extraction is not None and extraction.status == "ok":
        return extraction
    if extraction is None:
        extraction = InvoiceExtraction(document_id=document_id, created_at=now, currency="EUR")
        session.add(extraction)
    extraction.status = "failed"
    extraction.extractor = extractor_name
    extraction.model = model
    extraction.error_code = code
    extraction.error_message = message
    extraction.flags_json = "[]"
    extraction.updated_at = now
    session.flush()
    return extraction


def run_extraction(
    session: Session,
    storage: DocumentStorage,
    extractor: InvoiceExtractor,
    document_id: int,
) -> InvoiceExtraction:
    """build -> extract -> store in one go (tests, one-shot use). Failures are stored and re-raised."""
    request = build_request(session, storage, document_id)
    try:
        invoice = extractor.extract(request)
    except ExtractionError as exc:
        store_failure(session, document_id, extractor.name, exc, extractor.model)
        raise
    return store_result(session, document_id, extractor.name, extractor.model, invoice)


# --- review ----------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReviewResult:
    extraction: InvoiceExtraction
    warnings: tuple[str, ...] = ()  # relation warnings, shown on the page


def _as_invoice(parsed: ParsedReview) -> ExtractedInvoice:
    return ExtractedInvoice(
        kind=parsed.kind,
        supplier=_as_contact(parsed),
        invoice_number=parsed.invoice_number,
        invoice_date=parsed.invoice_date,
        due_date=parsed.due_date,
        currency=parsed.currency,
        total_excl_cents=parsed.total_excl_cents,
        total_vat_cents=parsed.total_vat_cents,
        total_incl_cents=parsed.total_incl_cents,
        lines=tuple(
            ExtractedLine(
                description=ln.description,
                amount_excl_cents=ln.amount_excl_cents,
                vat_code=ln.vat_code,
                vat_amount_cents=ln.vat_amount_cents,
                suggested_account_code=ln.account_code,
            )
            for ln in parsed.lines
        ),
    )


def _as_contact(parsed: ParsedReview) -> ExtractedContact:
    return ExtractedContact(
        name=parsed.supplier_name,
        kvk=parsed.supplier_kvk,
        btw_number=parsed.supplier_btw_number,
        iban=parsed.supplier_iban,
        address_line=parsed.supplier_address_line,
        postal_code=parsed.supplier_postal_code,
        city=parsed.supplier_city,
        country=parsed.supplier_country,
    )


def save_review(
    session: Session,
    document_id: int,
    data: ReviewInput,
    *,
    finish: bool,
) -> ReviewResult:
    """Validate and store the owner's corrections; `finish` marks it nagekeken.

    Raises ReviewValidationError (nothing is changed) with plain-Dutch messages.
    Flags are recomputed from the corrected data (our own checks only).
    `finish=True` also creates the supplier relation when it is new.
    """
    document = _editable_document(session, document_id)
    extraction = get_extraction(session, document_id)
    accounts, vat_rates = _account_refs(session), _vat_rates(session)
    parsed = parse_review(data, accounts=accounts, vat_codes=vat_rates, finish=finish)

    match = match_or_create_contact(session, _as_contact(parsed), "supplier", create=finish)
    flags = assess(_as_invoice(parsed), accounts, vat_rates, date.today())
    header, per_line = _split_flags(merge_flags([*flags, *_supplier_flags(match)]))

    now = _now()
    extraction.status = "ok"
    extraction.error_code = None
    extraction.error_message = None
    extraction.kind = parsed.kind
    extraction.supplier_name = parsed.supplier_name
    extraction.supplier_kvk = parsed.supplier_kvk
    extraction.supplier_btw_number = parsed.supplier_btw_number
    extraction.supplier_iban = parsed.supplier_iban
    extraction.supplier_address_line = parsed.supplier_address_line
    extraction.supplier_postal_code = parsed.supplier_postal_code
    extraction.supplier_city = parsed.supplier_city
    extraction.supplier_country = parsed.supplier_country
    extraction.contact_id = match.contact.id if match.contact is not None else None
    extraction.invoice_number = parsed.invoice_number
    extraction.invoice_date = parsed.invoice_date
    extraction.due_date = parsed.due_date
    extraction.currency = parsed.currency
    extraction.total_excl_cents = parsed.total_excl_cents
    extraction.total_vat_cents = parsed.total_vat_cents
    extraction.total_incl_cents = parsed.total_incl_cents
    extraction.flags_json = _dump(header)
    extraction.reviewed_at = now if finish else None
    extraction.updated_at = now
    session.flush()

    account_ids = _account_ids(session)
    rows = []
    for i, ln in enumerate(parsed.lines):
        rows.append(
            dict(
                description=ln.description,
                amount_excl_cents=ln.amount_excl_cents,
                vat_amount_cents=ln.vat_amount_cents,
                vat_code=ln.vat_code,
                account_id=account_ids.get(ln.account_code) if ln.account_code else None,
                flags_json=_dump(per_line.get(i, [])),
            )
        )
    _replace_lines(session, extraction, rows)
    _apply_learned_defaults(session, extraction)
    if document.status == "nieuw":
        mark_recognized(session, document_id)
    log.info("extraction reviewed document=%s finish=%s", document_id, finish)
    return ReviewResult(extraction, tuple(match.warnings))


# --- backend status ------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BackendStatus:
    kind: Literal["claude_cli", "anthropic_api", "unavailable"]
    available: bool
    message: str  # for the banner


def backend_status(settings: Settings) -> BackendStatus:
    """Which backend `auto` would use right now, with a plain-Dutch banner text."""
    from app.domain.extraction.extractors.factory import cli_status

    wanted = getattr(settings, "extraction_backend", "auto")
    key = settings.anthropic_api_key
    has_key = key is not None and bool(key.get_secret_value().strip())
    cli = cli_status(settings) if wanted in ("auto", "claude_cli") else None

    if cli == "ready":
        return BackendStatus("claude_cli", True, "Uitlezen verloopt via je Claude-abonnement")
    if wanted in ("auto", "anthropic_api") and has_key:
        return BackendStatus("anthropic_api", True, "Uitlezen verloopt via je API-sleutel")
    if cli == "missing" and wanted == "auto" and not has_key:
        return BackendStatus(
            "unavailable",
            False,
            "Claude is niet gevonden op deze computer. Installeer Claude Code en typ in "
            "Terminal: claude auth login. Of zet ANTHROPIC_API_KEY in het bestand .env.",
        )
    if wanted == "anthropic_api":
        return BackendStatus(
            "unavailable", False, "Er staat geen API-sleutel in .env. Zet ANTHROPIC_API_KEY in het bestand .env."
        )
    return BackendStatus(
        "unavailable",
        False,
        "Niet ingelogd bij Claude: open Terminal en typ claude auth login. "
        "Of zet ANTHROPIC_API_KEY in het bestand .env.",
    )
