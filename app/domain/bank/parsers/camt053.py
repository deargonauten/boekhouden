"""CAMT.053 (ISO 20022 bank-to-customer statement) parser, versions .02 and .08 (any .0x).

Namespaces are ignored (matching on local names). XML is parsed with defusedxml so
entity expansion and external entities are refused.
"""

import re
from datetime import date
from xml.etree.ElementTree import Element, tostring

from defusedxml import DefusedXmlException
from defusedxml import ElementTree as SafeET

from app.domain.bank.amounts import parse_amount
from app.domain.bank.iban import bank_from_iban
from app.domain.bank.parsers.base import (
    clean_iban,
    clean_reference,
    collapse,
    parse_error,
    require_eur,
)
from app.domain.bank.types import (
    PARSE_ERROR,
    BankImportError,
    ParsedStatement,
    ParsedTransaction,
)

_BIC_BANKS = {"INGB": "ing", "RABO": "rabobank", "ABNA": "abn_amro", "BUNQ": "bunq"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(el: Element | None, *path: str) -> Element | None:
    for name in path:
        if el is None:
            return None
        el = next((c for c in el if _local(c.tag) == name), None)
    return el


def _children(el: Element | None, name: str) -> list[Element]:
    return [] if el is None else [c for c in el if _local(c.tag) == name]


def _text(el: Element | None, *path: str) -> str | None:
    node = _child(el, *path)
    if node is None or node.text is None:
        return None
    value = node.text.strip()
    return value or None


def _iter(el: Element, name: str):
    return (e for e in el.iter() if _local(e.tag) == name)


def _parse_date(el: Element | None, where: str) -> date | None:
    if el is None:
        return None
    raw = _text(el, "Dt") or _text(el, "DtTm")
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise parse_error(where, f"heeft een ongeldige datum ('{raw}')") from exc


def _amount(el: Element | None, where: str) -> tuple[int, str | None]:
    if el is None or not (el.text or "").strip():
        raise parse_error(where, "heeft geen bedrag")
    cents = parse_amount(el.text, "en")
    return cents, el.get("Ccy")


def _signed(cents: int, indicator: str | None, where: str) -> int:
    # CdtDbtInd already states the booked effect on the balance, also for reversals (RvslInd).
    if indicator not in ("CRDT", "DBIT"):
        raise parse_error(where, "heeft geen bij/af-aanduiding (CdtDbtInd)")
    return cents if indicator == "CRDT" else -cents


def _party_name(party: Element | None) -> str | None:
    if party is None:
        return None
    return collapse(_text(party, "Nm") or _text(party, "Pty", "Nm") or "") or None


def _remittance(tx: Element | None, entry: Element) -> str:
    parts: list[str] = []
    if tx is not None:
        rmt = _child(tx, "RmtInf")
        if rmt is not None:
            parts += [(u.text or "") for u in _children(rmt, "Ustrd")]
            for strd in _children(rmt, "Strd"):
                ref = _text(strd, "CdtrRefInf", "Ref")
                if ref:
                    parts.append(ref)
        info = _text(tx, "AddtlTxInf")
        if info and not parts:
            parts.append(info)
    if not parts:
        parts.append(_text(entry, "AddtlNtryInf") or "")
    return collapse(" ".join(parts))


def _counterparty(tx: Element | None, positive: bool) -> tuple[str | None, str | None]:
    """Money in (positive) -> the debtor paid us; money out -> the creditor."""
    if tx is None:
        return None, None
    parties = _child(tx, "RltdPties")
    role, acct = ("Dbtr", "DbtrAcct") if positive else ("Cdtr", "CdtrAcct")
    name = _party_name(_child(parties, role))
    iban_raw = _text(parties, acct, "Id", "IBAN")
    return name, clean_iban(iban_raw)


def _node_text(el: Element) -> str:
    text = tostring(el, encoding="unicode")
    text = re.sub(r' xmlns(?::\w+)?="[^"]*"', "", text)
    return collapse(re.sub(r"(</?)\w+:", r"\1", text))


def _balance(stmt: Element, codes: tuple[str, ...], where: str) -> int | None:
    for bal in _children(stmt, "Bal"):
        code = _text(bal, "Tp", "CdOrPrtry", "Cd")
        if code in codes:
            cents, ccy = _amount(_child(bal, "Amt"), where + " (saldo)")
            require_eur(ccy, where)
            return _signed(cents, _text(bal, "CdtDbtInd"), where + " (saldo)")
    return None


class Camt053Parser:
    def detect(self, content: bytes) -> bool:
        return b"BkToCstmrStmt" in content

    def parse(self, content: bytes, hint_bank: str | None = None) -> ParsedStatement:
        try:
            root = SafeET.fromstring(content.lstrip())
        except DefusedXmlException as exc:
            raise BankImportError(
                PARSE_ERROR,
                "Dit XML-bestand bevat constructies die we om veiligheidsredenen weigeren. "
                "Download het afschrift opnieuw bij je bank.",
            ) from exc
        except Exception as exc:  # xml.etree.ElementTree.ParseError and friends
            raise BankImportError(
                PARSE_ERROR,
                "Het XML-bestand is beschadigd of onvolledig en kon niet worden gelezen. "
                "Download het afschrift opnieuw bij je bank.",
            ) from exc

        statements = list(_iter(root, "Stmt"))
        if not statements:
            raise BankImportError(
                PARSE_ERROR, "In dit CAMT.053-bestand staat geen afschrift (Stmt). Download het bestand opnieuw."
            )

        ibans: list[str] = []
        bank: str | None = None
        transactions: list[ParsedTransaction] = []
        opening = closing = None
        for s_idx, stmt in enumerate(statements, start=1):
            s_where = f"afschrift {s_idx}"
            acct = _child(stmt, "Acct")
            iban = clean_iban(_text(acct, "Id", "IBAN"))
            if iban and iban not in ibans:
                ibans.append(iban)
            require_eur(_text(acct, "Ccy"), f"Rekening in {s_where}")
            bic = _text(acct, "Svcr", "FinInstnId", "BICFI") or _text(acct, "Svcr", "FinInstnId", "BIC")
            bank = bank or (_BIC_BANKS.get(bic[:4].upper()) if bic else None) or bank_from_iban(iban)
            op = _balance(stmt, ("OPBD", "PRCD"), s_where)
            cl = _balance(stmt, ("CLBD",), s_where)
            if s_idx == 1:
                opening = op
            closing = cl
            for n_idx, entry in enumerate(_children(stmt, "Ntry"), start=1):
                transactions += self._entry(entry, f"{s_where}, boeking {n_idx}")
        if len(ibans) > 1:
            raise BankImportError(
                PARSE_ERROR,
                "In dit bestand staan afschriften van meerdere rekeningen. "
                "Download het afschrift per rekening en importeer ze apart.",
            )
        return ParsedStatement(
            account_iban=ibans[0] if ibans else None,
            currency="EUR",
            opening_cents=opening,
            closing_cents=closing,
            transactions=tuple(transactions),
            format="camt053",
            bank=bank,
        )

    def _entry(self, entry: Element, where: str) -> list[ParsedTransaction]:
        status = _text(entry, "Sts") or _text(entry, "Sts", "Cd")
        if status and status.upper() not in ("BOOK", "BOOKED"):
            return []  # pending/information entries are not booked yet
        e_cents, e_ccy = _amount(_child(entry, "Amt"), where)
        require_eur(e_ccy, where)
        indicator = _text(entry, "CdtDbtInd")
        reversal = (_text(entry, "RvslInd") or "").lower() == "true"
        booking = _parse_date(_child(entry, "BookgDt"), where)
        if booking is None:
            raise parse_error(where, "heeft geen boekingsdatum")
        value = _parse_date(_child(entry, "ValDt"), where)
        entry_ref = _text(entry, "AcctSvcrRef") or _text(entry, "NtryRef")
        raw = _node_text(entry)

        details = [t for nd in _children(entry, "NtryDtls") for t in _children(nd, "TxDtls")]
        if len(details) <= 1:
            tx = details[0] if details else None
            return [self._build(entry, tx, e_cents, indicator, reversal, booking, value, entry_ref, raw, where)]

        out = []
        total = 0
        for t_idx, tx in enumerate(details, start=1):
            t_where = f"{where}, onderdeel {t_idx}"
            amt_el = _child(tx, "Amt")
            if amt_el is None:
                amt_el = _child(tx, "AmtDtls", "TxAmt", "Amt")
            if amt_el is None:
                raise parse_error(t_where, "heeft geen eigen bedrag terwijl de boeking uit meerdere delen bestaat")
            cents, ccy = _amount(amt_el, t_where)
            require_eur(ccy, t_where)
            total += cents
            out.append(self._build(entry, tx, cents, indicator, reversal, booking, value, entry_ref, raw, t_where))
        if total != e_cents:
            raise parse_error(where, "heeft onderdelen die samen niet optellen tot het totaalbedrag")
        return out

    def _build(self, entry, tx, cents, indicator, reversal, booking, value, entry_ref, raw, where):
        amount = _signed(cents, indicator, where)
        if amount == 0:
            raise parse_error(where, "heeft een bedrag van 0")
        name, iban = _counterparty(tx, amount > 0)
        e2e = clean_reference(_text(tx, "Refs", "EndToEndId")) if tx is not None else None
        ref = (_text(tx, "Refs", "AcctSvcrRef") if tx is not None else None) or entry_ref
        return ParsedTransaction(
            booking_date=booking,
            value_date=value,
            amount_cents=amount,
            counterparty_name=name,
            counterparty_iban=iban,
            description=_remittance(tx, entry),
            end_to_end_id=e2e,
            bank_reference=collapse(ref) or None,
            raw=raw,
        )

