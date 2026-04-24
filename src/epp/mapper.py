"""
Rewizor GT EDI++ mapper — v1.12 spec.

Transforms raw invoice dicts (from DB or OCR) into fully-populated
:class:`EPPDocument` objects ready for the writer.

Supports all 12 Rewizor document types (FZ, FS, KZ, KS, FZK, FSK,
KZK, KSK, WB, RK, PK, DE) and the three supplier origins (PL / EU
/ NON-EU).

Key behaviours:

  - Auto-detects ``doc_type`` from OCR output when available.
  - Classifies origin (PL / EU / NON-EU) and picks the correct
    transaction type (field 55): 0=domestic (incl. OSS Polish-VAT),
    11=import of services (reverse charge).
  - Chooses VAT symbol and rate:
      * Polish VAT charged → "23" / "8" / "5" / "0" (rate >= 0)
      * Exempt domestic → "zw" (-1)
      * Reverse charge (foreign + 0 VAT) → "oo" (-5)
  - Builds a KONTRAHENCI card, GRUPYKONTRAHENTOW entry, WYMAGALNOSCMPP
    row, DATYZAKONCZENIA row and DOKUMENTYZNACZNIKIJPKVAT row for each
    document so the writer can assemble every v1.12 section.
  - Computes fields 36/37 (paid-at-receipt / amount-due) based on
    payment method to avoid Rewizor's 'Dekret nie bilansuje się'
    error.
  - Handles corrections (FZK/FSK/KZK/KSK) with negative amounts.
"""

import logging
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Union

from src.epp.classifier import classify_supplier
from src.epp.constants import (
    CONTRACTOR_GROUP_BUYERS,
    CONTRACTOR_GROUP_SUPPLIERS,
    CONTRACTOR_TYPE_BOTH,
    CORRECTION_DOC_TYPES,
    DOC_TYPE_PURCHASE_INVOICE,
    DOC_TYPE_TO_REGISTER,
    NON_VAT_DOC_TYPES,
    PAYMENT_CASH,
    PAYMENT_METHOD_ALIASES,
    PAYMENT_TRANSFER,
    PURCHASE_DOC_TYPES,
    RATE_TO_SYMBOL,
    TRANSACTION_CODE_IMPORT_SERVICES,
    TXN_TYPE_DOMESTIC,
    TXN_TYPE_IMPORT_SERVICES,
    TXN_TYPE_REVERSE_CHARGE_SERVICES,
    VALID_DOC_TYPES,
    VALID_PAYMENT_METHODS,
    VAT_RATE_EXEMPT,
    VAT_RATE_REVERSE_CHARGE,
    VAT_SYMBOL_0,
    VAT_SYMBOL_23,
    VAT_SYMBOL_EXEMPT,
    VAT_SYMBOL_NOT_APPLICABLE,
    VAT_SYMBOL_REVERSE_CHARGE,
    polish_country_name,
)
from src.epp.schemas import (
    EPPContractor,
    EPPDocument,
    EPPHeader,
    EPPJpkFlags,
    EPPVatRow,
)

logger = logging.getLogger(__name__)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _default_payment_term_days() -> int:
    """Business default for the payment term when OCR can't find a due date.

    Configured via ``EPP_DEFAULT_PAYMENT_TERM_DAYS`` (default 14 days — the
    most common Polish B2B term). Set to 0 to disable the fallback entirely
    and leave NAGLOWEK field 35 empty.
    """
    raw = os.getenv("EPP_DEFAULT_PAYMENT_TERM_DAYS", "14")
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 14


def _coerce_iso_date(value: Optional[Union[str, date, datetime]]) -> Optional[str]:
    """Return *value* as an ISO ``YYYY-MM-DD`` string, or ``None`` if empty/unknown.

    psycopg2 hands ``DATE`` columns back as ``datetime.date`` objects, so any
    function that treats those values as strings (``strptime``, ``.strip()``)
    needs this coercion at the boundary. Accepts the same loose formats as
    :func:`src.epp.utils.format_epp_date` for callers that already have an
    OCR-extracted string.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if not text:
        return None
    if "T" in text:
        text = text.split("T", 1)[0]
    elif " " in text:
        text = text.split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
                "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y",
                "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _derive_payment_due_date(
    explicit_due: Optional[Union[str, date, datetime]],
    issue_date: Optional[Union[str, date, datetime]],
    payment_method: str,
) -> Optional[str]:
    """Pick a payment due date.

    Order of preference:
      1. Explicit value from OCR / caller.
      2. For bank transfers (``przelew``, ``karta``, ``kompensata``):
         issue_date + ``EPP_DEFAULT_PAYMENT_TERM_DAYS`` (default 14).
      3. For cash (``gotówka``): issue_date (paid on the spot).
      4. Otherwise ``None`` — leave NAGLOWEK field 35 empty.

    ``explicit_due`` and ``issue_date`` may be strings *or* ``datetime.date``
    objects — the latter is what psycopg2 returns for ``DATE`` columns, so
    the DB-driven regenerate/export paths feed us those directly.
    """
    explicit_iso = _coerce_iso_date(explicit_due)
    if explicit_iso:
        return explicit_iso

    issue_iso = _coerce_iso_date(issue_date)
    if not issue_iso:
        return None

    dt = datetime.strptime(issue_iso, "%Y-%m-%d")

    # Cash is "due" on the spot; everything else gets the business-default term.
    if payment_method == "gotówka":
        return dt.strftime("%Y-%m-%d")
    days = _default_payment_term_days()
    if days <= 0:
        return None
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")


# Common corporate-form suffixes stripped from contractor names before
# slugging, so "Surfshark B.V." / "Amazon Web Services, Inc." / "Stripe, Inc."
# produce stable human-readable codes instead of suffix-polluted slugs.
_COMPANY_SUFFIX_TOKENS = {
    # English
    "INC", "LLC", "LTD", "LIMITED", "CORP", "CORPORATION", "CO",
    "COMPANY", "PLC", "LLP", "LP",
    # Polish
    "SP", "ZOO", "Z", "O", "OO", "SPZOO", "SA", "SC", "SK", "SKA",
    # German / Swiss
    "GMBH", "AG", "KG", "OHG", "MBH",
    # Dutch / Belgian
    "BV", "NV", "CV", "VOF",
    # French / Italian / Spanish
    "SARL", "SRL", "SAS", "SPA", "SRLS",
    # Irish / Nordic
    "AB", "AS", "OY", "OYJ",
}


def _contractor_code(name: Optional[str], nip: Optional[str] = None) -> str:
    """Derive a Rewizor-compatible contractor code.

    Convention: UPPER_CASE with underscores, max 20 chars (KONTRAHENCI
    field 2 limit). Drops corporate-form noise tokens ("B.V.", "Inc.",
    "Sp. z o.o.") so multiple invoices from the same supplier all map to
    the same stable slug. Falls back to NIP digits if name is empty.
    """
    if name:
        # Normalise for slugging:
        #   - Remove dots entirely so "B.V." / "Sp." / "o.o." compress into
        #     single uppercase tokens "BV" / "SP" / "OO" (matching the
        #     entries in _COMPANY_SUFFIX_TOKENS).
        #   - Replace commas and any other punctuation with whitespace so
        #     they become token boundaries.
        cleaned = name.upper().replace(".", "")
        cleaned = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in cleaned)
        tokens = [t for t in cleaned.split() if t]
        # Drop corporate-form suffix tokens from the tail only — we only
        # want to strip noise at the END of the name, not the middle
        # (e.g. "ABB Ltd Poland" keeps "POLAND").
        while tokens and tokens[-1] in _COMPANY_SUFFIX_TOKENS:
            tokens.pop()
        sym = "_".join(tokens)
        sym = sym[:20].rstrip("_")
        while "__" in sym:
            sym = sym.replace("__", "_")
        if sym:
            return sym
    if nip:
        cleaned = "".join(c for c in nip if c.isdigit())
        if cleaned:
            return cleaned[:20]
    return "UNKNOWN"


def _is_foreign_supplier(invoice: Dict[str, Any]) -> bool:
    return classify_supplier(invoice)["type"] != "PL"


def _is_reverse_charge(invoice: Dict[str, Any]) -> bool:
    """True when the invoice qualifies for reverse charge (import of services).

    Foreign supplier with zero VAT on the invoice → buyer self-assesses
    Polish VAT (the "oo" symbol, transaction type 11).
    """
    vat = _safe_float(invoice.get("vat_amount"))
    if vat != 0.0:
        return False
    return _is_foreign_supplier(invoice)


def _normalise_payment_method(value: Any) -> str:
    """Map any input (P/G/K/O, 'przelew', 'transfer', ...) to the canonical Rewizor name.

    Unknown / missing → "przelew" (the overwhelmingly common case for
    B2B invoices). Returns the empty string only if the caller explicitly
    disabled payment for this document type (e.g. a credit-note).
    """
    if value is None:
        return PAYMENT_TRANSFER
    key = str(value).strip().lower()
    if not key:
        return PAYMENT_TRANSFER
    if key in PAYMENT_METHOD_ALIASES:
        return PAYMENT_METHOD_ALIASES[key]
    # Direct match against canonical names
    if key in VALID_PAYMENT_METHODS:
        return key
    return PAYMENT_TRANSFER


def _pick_vat_symbol(rate: float, reverse_charge: bool) -> str:
    """Pick the EDI++ symbol for a given rate. Respects reverse charge."""
    if reverse_charge:
        return VAT_SYMBOL_REVERSE_CHARGE
    if rate < 0:
        # Negative rate markers: caller should map explicitly. Default to "zw".
        return VAT_SYMBOL_EXEMPT
    return RATE_TO_SYMBOL.get(round(rate, 2), VAT_SYMBOL_23)


def _infer_vat_rows(
    net: float, vat: float, gross: float, reverse_charge: bool
) -> List[EPPVatRow]:
    """Build a single-rate VAT breakdown from totals when no vat_breakdown is given."""
    if reverse_charge:
        return [
            EPPVatRow(
                vat_symbol=VAT_SYMBOL_REVERSE_CHARGE,
                vat_rate=VAT_RATE_REVERSE_CHARGE,
                net_at_rate=net,
                vat_at_rate=0.0,
                gross_at_rate=gross,
                final_general_net=net,
                final_general_vat=0.0,
                final_general_gross=gross,
            )
        ]

    if net > 0 and vat > 0:
        effective_rate = round((vat / net) * 100, 0)
    elif net > 0 and vat == 0:
        effective_rate = 0.0
    else:
        effective_rate = 23.0

    symbol = _pick_vat_symbol(effective_rate, reverse_charge=False)

    return [
        EPPVatRow(
            vat_symbol=symbol,
            vat_rate=effective_rate,
            net_at_rate=net,
            vat_at_rate=vat,
            gross_at_rate=gross,
            final_general_net=net,
            final_general_vat=vat,
            final_general_gross=gross,
        )
    ]


def _build_vat_rows_from_breakdown(
    breakdown: List[Dict[str, Any]], reverse_charge: bool
) -> List[EPPVatRow]:
    rows: List[EPPVatRow] = []
    for row in breakdown:
        raw_symbol = str(row.get("symbol") or "").strip()
        raw_rate = _safe_float(row.get("rate"))
        net = _safe_float(row.get("net"))
        vat = _safe_float(row.get("vat"))
        gross = _safe_float(row.get("gross"))

        if reverse_charge or raw_symbol.lower() == VAT_SYMBOL_REVERSE_CHARGE or raw_symbol == "00":
            symbol_out = VAT_SYMBOL_REVERSE_CHARGE
            rate_out = VAT_RATE_REVERSE_CHARGE
            vat = 0.0
        elif raw_symbol.lower() in {VAT_SYMBOL_EXEMPT, "zw."}:
            symbol_out = VAT_SYMBOL_EXEMPT
            rate_out = VAT_RATE_EXEMPT
        elif raw_symbol.lower() in {VAT_SYMBOL_NOT_APPLICABLE, "np."}:
            # OCR sometimes emits "np" for foreign services not subject to PL VAT.
            # When combined with a foreign supplier this should already have
            # been normalised to reverse-charge upstream; keep the symbol as a
            # safe fallback.
            symbol_out = VAT_SYMBOL_NOT_APPLICABLE
            rate_out = VAT_RATE_EXEMPT
        else:
            symbol_out = raw_symbol or _pick_vat_symbol(raw_rate, False)
            rate_out = raw_rate

        rows.append(
            EPPVatRow(
                vat_symbol=symbol_out,
                vat_rate=rate_out,
                net_at_rate=net,
                vat_at_rate=vat,
                gross_at_rate=gross,
                final_general_net=net,
                final_general_vat=vat,
                final_general_gross=gross,
            )
        )

    return rows


def _contractor_nip_for_header(raw_nip: str, country_code: str) -> str:
    """Return NIP in the correct format for NAGLOWEK field 18.

    For foreign EU suppliers the NIP should include the 2-letter country
    prefix (e.g. "NL862287339B01"). For Polish suppliers we emit the bare
    digits — matching Rewizor's expectation. For non-EU suppliers without
    any VAT/tax identifier on the invoice we synthesise a placeholder
    from the country code so Rewizor has *something* to hang the
    contractor card on; otherwise it rejects reverse-charge transactions
    with "Nieprawidłowa transakcja VAT zakupu".
    """
    cleaned = (str(raw_nip).strip() if raw_nip else "")
    if cleaned:
        # Already prefixed → trust it.
        if len(cleaned) >= 3 and cleaned[:2].isalpha() and cleaned[:2].upper() != "PL":
            return cleaned.upper()
        digits = "".join(c for c in cleaned if c.isdigit() or c.isalpha())
        if country_code and country_code.upper() != "PL" and not (
            len(digits) >= 2 and digits[:2].isalpha()
        ):
            return f"{country_code.upper()}{digits}"
        # Polish / unknown → digits only
        return "".join(c for c in cleaned if c.isdigit())

    # Empty NIP: synthesise from country code for non-EU suppliers so
    # reverse-charge transactions have an identifier Rewizor can accept.
    if country_code and country_code.upper() != "PL":
        return f"{country_code.upper()}0000000000"
    return ""


# ── Public API ──────────────────────────────────────────────────────────────

def map_invoice_to_epp(
    invoice: Dict[str, Any],
    *,
    doc_type: Optional[str] = None,
) -> EPPDocument:
    """Convert a single invoice dict into a fully-populated :class:`EPPDocument`.

    The *invoice* dict may come from:

      - The Rewizor OCR service (rich data with ``doc_type``,
        ``vat_breakdown``, ``exchange_rate``, ...).
      - The DB repository (minimal: ``invoice_number``, ``net_amount``,
        ...).

    When *doc_type* is not provided explicitly, it is read from
    ``invoice["doc_type"]`` (set by the OCR service) or falls back to
    ``"FZ"``.

    The returned document contains the header, VAT rows, contractor
    card, MPP flag, completion date and JPK_V7 flags — enough for the
    writer to emit a complete v1.12 EPP file.
    """
    # ── Document type ──
    if doc_type is None:
        ocr_type = (invoice.get("doc_type") or "").strip().upper()
        doc_type = ocr_type if ocr_type in VALID_DOC_TYPES else DOC_TYPE_PURCHASE_INVOICE
    doc_type = doc_type.strip().upper()
    if doc_type not in VALID_DOC_TYPES:
        doc_type = DOC_TYPE_PURCHASE_INVOICE

    is_correction = doc_type in CORRECTION_DOC_TYPES
    is_non_vat = doc_type in NON_VAT_DOC_TYPES
    is_purchase = doc_type in PURCHASE_DOC_TYPES

    # Corrections reference the original document — NAGLOWEK fields 8 & 9.
    corrected_doc_number = invoice.get("corrected_doc_number") or "" if is_correction else ""
    corrected_doc_date = (
        _coerce_iso_date(invoice.get("corrected_doc_date")) if is_correction else None
    )

    # ── Amounts ──
    net = _safe_float(invoice.get("net_amount"))
    vat = _safe_float(invoice.get("vat_amount"))
    gross = _safe_float(invoice.get("gross_amount"))
    if gross == 0.0 and net > 0:
        gross = round(net + vat, 2)

    if net == 0.0 and vat == 0.0 and gross == 0.0 and not is_non_vat:
        logger.warning(
            "Invoice %s has all-zero amounts", invoice.get("invoice_number")
        )

    # ── Dates ──
    # psycopg2 hands DATE columns back as datetime.date objects; coerce every
    # date field to ISO string here so the header schema (which demands strs)
    # and downstream strptime helpers don't need to think about types.
    issue_date = (
        _coerce_iso_date(invoice.get("date"))
        or _coerce_iso_date(invoice.get("issue_date"))
        or ""
    )
    if not issue_date:
        logger.warning(
            "Invoice %s has no issue date, EPP may be incomplete",
            invoice.get("invoice_number"),
        )
    sale_date = _coerce_iso_date(invoice.get("sale_date")) or issue_date
    receipt_date = _coerce_iso_date(invoice.get("receipt_date")) or issue_date
    # Resolved further below (after payment_method is canonicalised).
    payment_due_date: Optional[str] = None

    # ── Contractor & origin classification ──
    raw_nip = invoice.get("contractor_nip") or invoice.get("nip") or ""
    contractor_name = invoice.get("contractor_name") or invoice.get("vendor") or ""
    code = _contractor_code(contractor_name, raw_nip)

    origin = classify_supplier(invoice)
    origin_type = origin["type"]
    iso = (origin.get("code") or invoice.get("contractor_country") or "").upper()[:2]
    country_pl = polish_country_name(iso, default="Polska")
    is_eu_flag = 1 if origin_type == "EU" else 0

    header_nip = _contractor_nip_for_header(raw_nip, iso)

    # ── Currency / FX ──
    currency = (invoice.get("currency") or "PLN").strip().upper()
    raw_rate = invoice.get("exchange_rate")
    try:
        fx_rate = round(float(raw_rate), 4) if raw_rate is not None else 1.0
    except (TypeError, ValueError):
        fx_rate = 1.0
    if fx_rate == 0.0:
        fx_rate = 1.0
    if currency != "PLN" and fx_rate == 1.0:
        logger.warning(
            "Invoice %s: currency is %s but exchange_rate is 1.0 – "
            "Rewizor GT needs a real NBP rate for foreign-currency invoices",
            invoice.get("invoice_number"),
            currency,
        )

    # ── Reverse charge detection ──
    # Rewizor's posting scheme differs per origin:
    #   * EU supplier → type 11 (IMUn, import of services, intra-community)
    #   * Non-EU supplier → type 21 (OOu, reverse charge on services)
    # Using 11 for non-EU triggers "Nieprawidłowa transakcja VAT zakupu".
    reverse_charge = (not is_non_vat) and _is_reverse_charge(invoice)
    if reverse_charge:
        if origin_type == "EU":
            transaction_type = TXN_TYPE_IMPORT_SERVICES          # 11 – IMUn
        else:
            transaction_type = TXN_TYPE_REVERSE_CHARGE_SERVICES  # 21 – OOu
        kod_transakcji = TRANSACTION_CODE_IMPORT_SERVICES
    else:
        transaction_type = TXN_TYPE_DOMESTIC
        kod_transakcji = ""

    # ── Payment method & fields 36/37 ──
    payment_method = _normalise_payment_method(invoice.get("payment_method"))
    # Non-VAT docs don't carry a payment method on their face
    if is_non_vat:
        payment_method = ""

    # Payment due date: prefer OCR, then fall back to a business default
    # (issue + N days for bank transfer, same-day for cash). Never silently
    # fall back to issue_date unconditionally — that produced "already
    # overdue" journal entries in Rewizor.
    payment_due_date = _derive_payment_due_date(
        invoice.get("payment_due_date"), issue_date, payment_method
    )

    if payment_method == PAYMENT_CASH:
        # Cash paid immediately: field 36 = full gross, field 37 = 0.
        paid_at_receipt = gross
        amount_due = 0.0
    elif payment_method:
        # Bank transfer / card / compensation: field 36 = 0, field 37 = gross.
        paid_at_receipt = 0.0
        amount_due = gross
    else:
        # Non-VAT doc or explicit no-payment
        paid_at_receipt = 0.0
        amount_due = 0.0

    # ── Document numbering ──
    invoice_number = (invoice.get("invoice_number") or "").strip()
    # Place of issue: prefer an explicit value on the invoice; otherwise
    # leave blank and let the writer substitute the EPPInfo sender city
    # (i.e. the accountant's own city).
    place_of_issue = invoice.get("place_of_issue") or ""

    # ── Notes (49) ──
    notes_parts: List[str] = []
    if invoice.get("notes"):
        notes_parts.append(str(invoice["notes"]))
    if invoice.get("transaction_id"):
        notes_parts.append(f"Transaction ID: {invoice['transaction_id']}")
    notes = " | ".join(notes_parts)

    # ── Build the NAGLOWEK header ──
    header = EPPHeader(
        doc_type=doc_type,
        status=1,
        fiscal_flag=0,
        numeric_doc_number="1",
        supplier_invoice_number=invoice_number,
        user_number_suffix="",
        full_document_number=invoice_number,
        corrected_doc_number=corrected_doc_number,
        corrected_doc_date=corrected_doc_date,
        contractor_code=code,
        contractor_short_name=contractor_name,
        contractor_full_name=contractor_name,
        contractor_city=invoice.get("contractor_city") or "",
        contractor_postal_code=invoice.get("contractor_postal_code") or "",
        contractor_street=invoice.get("contractor_street") or "",
        contractor_nip=header_nip,
        category_name=("Sprzedaż" if not is_purchase else "Zakup"),
        category_subtitle=(
            "Sprzedaż towarów lub usług" if not is_purchase else "Zakup towarów lub usług"
        ),
        place_of_issue=place_of_issue,
        issue_date=issue_date,
        sale_date=sale_date,
        receipt_date=receipt_date,
        vat_lines_count=1,  # updated below once VAT rows are built
        priced_by_net=1,
        active_price_list="Cena ostatniej dost.",
        net_value=net,
        vat_value=vat,
        gross_value=gross,
        cost=net,
        discount_name="",
        discount_percent=0.0,
        payment_method=payment_method,
        payment_due_date=payment_due_date,
        paid_at_receipt=paid_at_receipt,
        amount_due=amount_due,
        total_rounding=0,
        vat_rounding=0,
        auto_recalculate=1,
        extended_status=0,
        person_issued="",
        person_received="Szef",
        currency=currency,
        fx_rate=fx_rate,
        notes=notes,
        transaction_type=transaction_type,
        contractor_country_name=country_pl,
        contractor_country_prefix=iso or "PL",
        contractor_is_eu=is_eu_flag,
    )

    # Stash the kod_transakcji in notes if no dedicated field (we don't have
    # one in NAGLOWEK — it used to live in field 9 but that's "corrected
    # document number" in the v1.12 spec). Rewizor derives the posting
    # scheme from transaction_type alone, so we simply log it for traceability.
    if kod_transakcji:
        logger.debug(
            "Invoice %s classified as %s (transaction_type=%s)",
            invoice_number, kod_transakcji, transaction_type,
        )

    # ── VAT rows ──
    if is_non_vat:
        vat_rows: List[EPPVatRow] = [
            EPPVatRow(
                vat_symbol=VAT_SYMBOL_0,
                vat_rate=0.0,
                net_at_rate=abs(gross),
                vat_at_rate=0.0,
                gross_at_rate=abs(gross),
                final_general_net=abs(gross),
                final_general_vat=0.0,
                final_general_gross=abs(gross),
            )
        ]
    else:
        vat_breakdown: Optional[List[Dict[str, Any]]] = invoice.get("vat_breakdown")
        if vat_breakdown:
            vat_rows = _build_vat_rows_from_breakdown(vat_breakdown, reverse_charge)
        else:
            vat_rows = _infer_vat_rows(net, vat, gross, reverse_charge)

    header.vat_lines_count = len(vat_rows)

    # ── KONTRAHENCI card ──
    contractor = EPPContractor(
        contractor_type=CONTRACTOR_TYPE_BOTH,
        code=code,
        short_name=contractor_name,
        full_name=contractor_name,
        city=invoice.get("contractor_city") or "",
        postal_code=invoice.get("contractor_postal_code") or "",
        street=invoice.get("contractor_street") or "",
        nip=header_nip,
        country_name=country_pl,
        country_prefix=iso or "PL",
        is_eu=is_eu_flag,
        iso_country_code=iso or "PL",
    )

    contractor_group = (
        CONTRACTOR_GROUP_SUPPLIERS if is_purchase else CONTRACTOR_GROUP_BUYERS
    )

    # ── JPK_V7 flags ──
    jpk_full_key = f"{doc_type} {invoice_number}".strip()
    jpk_flags = EPPJpkFlags(full_document_number=jpk_full_key)
    if reverse_charge and not is_purchase:
        # Sales-side reverse charge (rare): set TP flag? Leave all zeros
        # unless the caller provides explicit flags.
        pass
    # Per the EDI++ v1.12 spec, the JPK_V7 IMP flag is reserved for
    # "Import towarów" (import of GOODS cleared through Polish customs).
    # Import of services carries no JPK flag — reverse-charge treatment is
    # conveyed entirely by VAT symbol "oo" + transaction_type=11. Leaving
    # all flags at 0 is correct for non-EU service imports.

    return EPPDocument(
        header=header,
        vat_rows=vat_rows,
        contractor=contractor,
        contractor_group=contractor_group,
        mpp_required=0,
        completion_date=sale_date,
        jpk_flags=jpk_flags,
    )


# Re-export DOC_TYPE_TO_REGISTER so legacy callers keep working.
__all__ = ["map_invoice_to_epp", "DOC_TYPE_TO_REGISTER"]
