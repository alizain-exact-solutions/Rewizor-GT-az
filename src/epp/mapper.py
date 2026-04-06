"""
Rewizor GT EDI++ mapper.

Transforms raw invoice dicts (from DB or OCR) into EPP Pydantic models
ready for the EPP writer.

Supports all 12 Rewizor document types:
  FZ, FS, KZ, KS, FZK, FSK, KZK, KSK, WB, RK, PK, DE

Key behaviours:
  - Auto-detects doc_type from OCR output when available
  - Detects reverse charge (foreign supplier, 0 VAT) → symbol "00", rate -5.00
  - Formats contractor symbol as UPPER_UNDERSCORE (matching Rewizor conventions)
  - Maps all 51 fields of the [NAGLOWEK] section
  - Sets correct rodzaj_rejestru (register type) per doc type
  - Handles correction docs (FZK, FSK, KZK, KSK) with negative amounts
"""

import logging
from typing import Any, Dict, List, Optional

from src.epp.constants import (
    CORRECTION_DOC_TYPES,
    DOC_TYPE_PURCHASE_INVOICE,
    DOC_TYPE_TO_REGISTER,
    NON_VAT_DOC_TYPES,
    PAYMENT_TRANSFER,
    RATE_TO_SYMBOL,
    REGISTER_PURCHASE,
    TRANSACTION_CODE_IMPORT_SERVICES_EU,
    TRANSACTION_CODE_IMPORT_SERVICES_NON_EU,
    VALID_DOC_TYPES,
    VAT_RATE_EXEMPT,
    VAT_RATE_NOT_APPLICABLE,
    VAT_RATE_REVERSE_CHARGE,
    VAT_SYMBOL_23,
    VAT_SYMBOL_EXEMPT,
    VAT_SYMBOL_NOT_APPLICABLE,
    VAT_SYMBOL_REVERSE_CHARGE,
    VALID_PAYMENT_METHODS,
)
from src.epp.classifier import classify_supplier
from src.epp.schemas import EPPDocument, EPPHeader, EPPVatRow

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _contractor_symbol(name: Optional[str], nip: Optional[str] = None) -> str:
    """Derive a Rewizor-compatible contractor symbol.

    Convention: UPPER_CASE with underscores, max 40 chars.
    Falls back to NIP digits if name is empty.
    """
    if name:
        sym = name.strip().replace(" ", "_").replace(",", "").upper()[:40]
        if sym:
            return sym
    if nip:
        cleaned = "".join(c for c in nip if c.isdigit())
        if cleaned:
            return cleaned
    return "UNKNOWN"


def _is_foreign_supplier(invoice: Dict[str, Any]) -> bool:
    """True when the supplier is non-Polish (EU or NON-EU)."""
    return classify_supplier(invoice)["type"] != "PL"


def _is_import_uslug(invoice: Dict[str, Any]) -> bool:
    """True when the invoice qualifies as import usług.

    Foreign supplier + zero VAT on the invoice → buyer must
    self-assess VAT (reverse charge) in Poland.
    """
    vat = _safe_float(invoice.get("vat_amount"))
    if vat != 0.0:
        return False
    return _is_foreign_supplier(invoice)


def _infer_vat_rows(
    net: float,
    vat: float,
    gross: float,
    reverse_charge: bool,
) -> List[EPPVatRow]:
    """Build a single-rate VAT breakdown when only totals are available."""
    if reverse_charge:
        return [
            EPPVatRow(
                vat_symbol=VAT_SYMBOL_NOT_APPLICABLE,
                vat_rate=VAT_RATE_NOT_APPLICABLE,
                net_amount=net,
                vat_amount=0.0,
                gross_amount=gross,
            )
        ]

    if net > 0 and vat > 0:
        effective_rate = round((vat / net) * 100, 0)
    elif net > 0 and vat == 0:
        effective_rate = 0.0
    else:
        effective_rate = 23.0

    symbol = RATE_TO_SYMBOL.get(effective_rate, str(int(effective_rate)))

    return [
        EPPVatRow(
            vat_symbol=symbol,
            vat_rate=effective_rate,
            net_amount=net,
            vat_amount=vat,
            gross_amount=gross,
        )
    ]


def map_invoice_to_epp(
    invoice: Dict[str, Any],
    *,
    doc_type: Optional[str] = None,
) -> EPPDocument:
    """Convert a single invoice dict into an ``EPPDocument``.

    The *invoice* dict may come from either:
    - The Rewizor OCR service (rich data with ``doc_type``, ``vat_breakdown``, etc.)
    - The DB repository (minimal: ``invoice_number``, ``net_amount``, …)

    When *doc_type* is not provided, it is read from ``invoice["doc_type"]``
    (set by the OCR service).  Falls back to ``FZ`` (purchase invoice).

    Returns an ``EPPDocument`` ready for the EPP writer.
    """
    # ── Resolve document type ────────────────────────────────────────────
    if doc_type is None:
        ocr_type = (invoice.get("doc_type") or "").strip().upper()
        doc_type = ocr_type if ocr_type in VALID_DOC_TYPES else DOC_TYPE_PURCHASE_INVOICE

    is_correction = doc_type in CORRECTION_DOC_TYPES
    is_non_vat = doc_type in NON_VAT_DOC_TYPES
    net = _safe_float(invoice.get("net_amount"))
    vat = _safe_float(invoice.get("vat_amount"))
    gross = _safe_float(invoice.get("gross_amount"))
    if gross == 0.0 and net > 0:
        gross = round(net + vat, 2)

    # Validate that we have at least some amount data
    if net == 0.0 and vat == 0.0 and gross == 0.0 and not is_non_vat:
        logger.warning("Invoice %s has all-zero amounts",
                       invoice.get("invoice_number"))

    issue_date = invoice.get("date") or invoice.get("issue_date") or ""
    if not issue_date:
        logger.warning("Invoice %s has no issue date, EPP may be incomplete",
                       invoice.get("invoice_number"))

    sale_date = invoice.get("sale_date") or issue_date
    receipt_date = invoice.get("receipt_date") or issue_date

    contractor_nip = invoice.get("contractor_nip") or invoice.get("nip") or ""
    contractor_name = invoice.get("contractor_name") or invoice.get("vendor") or ""
    symbol = _contractor_symbol(contractor_name, contractor_nip)

    currency = (invoice.get("currency") or "PLN").strip().upper()
    raw_rate = invoice.get("exchange_rate")
    try:
        exchange_rate = round(float(raw_rate), 4) if raw_rate is not None else 1.0
    except (TypeError, ValueError):
        exchange_rate = 1.0
    if exchange_rate == 0.0:
        exchange_rate = 1.0

    reverse_charge = _is_import_uslug(invoice)
    origin = classify_supplier(invoice)["type"]

    raw_payment_method = (invoice.get("payment_method") or "").strip().upper()
    payment_method = raw_payment_method if raw_payment_method in VALID_PAYMENT_METHODS else ""
    if origin != "PL":
        payment_method = ""
    payment_due_date = invoice.get("payment_due_date") or issue_date

    register_type = DOC_TYPE_TO_REGISTER.get(doc_type, REGISTER_PURCHASE)

    # Transaction classification for foreign services
    if reverse_charge and origin == "EU":
        kod_transakcji = TRANSACTION_CODE_IMPORT_SERVICES_EU
    elif reverse_charge and origin == "NON_EU":
        kod_transakcji = TRANSACTION_CODE_IMPORT_SERVICES_NON_EU
    else:
        kod_transakcji = ""

    header = EPPHeader(
        doc_type=doc_type,
        rodzaj_rejestru=register_type,
        rodzaj_dokumentu=1 if is_correction else 0,
        doc_number=invoice.get("invoice_number") or "",
        numer_oryginalny=f"{doc_type} {invoice.get('invoice_number') or ''}".strip(),
        contractor_symbol=symbol,
        contractor_code=symbol,
        contractor_name=contractor_name,
        contractor_street=invoice.get("contractor_street") or "",
        contractor_city=invoice.get("contractor_city") or "",
        contractor_postal_code=invoice.get("contractor_postal_code") or "",
        contractor_region=invoice.get("contractor_region") or "",
        contractor_country=invoice.get("contractor_country") or "",
        contractor_nip=contractor_nip,
        kod_transakcji=kod_transakcji,
        issue_date=issue_date,
        sale_date=sale_date,
        receipt_date=receipt_date,
        net_total=net,
        vat_total=vat,
        gross_total=gross,
        payment_method=payment_method,
        amount_paid=_safe_float(invoice.get("amount_paid")),
        payment_due_date=payment_due_date,
        field_35=gross,
        currency=currency,
        exchange_rate=exchange_rate,
        flag_50=1 if reverse_charge else 0,
    )

    # ── VAT breakdown ────────────────────────────────────────────────────
    if is_non_vat:
        vat_rows: List[EPPVatRow] = [
            EPPVatRow(
                vat_symbol="0",
                vat_rate=0.0,
                net_amount=abs(gross),
                vat_amount=0.0,
                gross_amount=abs(gross),
            )
        ]
        return EPPDocument(header=header, vat_rows=vat_rows)

    vat_breakdown: Optional[List[Dict[str, Any]]] = invoice.get("vat_breakdown")

    if vat_breakdown:
        vat_rows: List[EPPVatRow] = []
        for row in vat_breakdown:
            raw_symbol = str(row.get("symbol", ""))
            raw_rate = _safe_float(row.get("rate"))

            if raw_symbol == VAT_SYMBOL_REVERSE_CHARGE or raw_symbol == "00" or reverse_charge:
                symbol_out = VAT_SYMBOL_NOT_APPLICABLE
                rate_out = VAT_RATE_NOT_APPLICABLE
            else:
                symbol_out = raw_symbol or RATE_TO_SYMBOL.get(raw_rate, VAT_SYMBOL_23)
                rate_out = raw_rate

            vat_rows.append(
                EPPVatRow(
                    vat_symbol=symbol_out,
                    vat_rate=rate_out,
                    net_amount=_safe_float(row.get("net")),
                    vat_amount=_safe_float(row.get("vat")),
                    gross_amount=_safe_float(row.get("gross")),
                )
            )
    else:
        vat_rows = _infer_vat_rows(net, vat, gross, reverse_charge)

    return EPPDocument(header=header, vat_rows=vat_rows)
