"""
Rewizor GT export service — orchestrator (single-tenant).

Workflow:
  Upload PDF → Rewizor OCR → NBP FX enrichment → EPP mapping → EPP bytes
  → persist in ``exports`` table.

The sender / business details that populate the EPP [INFO] section are
loaded from the ``business_details`` singleton table; the admin manages
that row through ``/api/v1/business-details``. If the row is missing we
raise :class:`BusinessDetailsNotConfigured` so the API can return 412.
"""

import glob
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from src.core.db import get_connection
from src.core.settings import (
    BusinessDetailsNotConfigured,
    build_epp_info,
    get_payment_term_days,
)
from src.epp.classifier import classify_supplier
from src.epp.epp_writer import generate_epp_bytes
from src.epp.mapper import _coerce_iso_date, map_invoice_to_epp
from src.epp.schemas import EPPDocument, EPPInfo
from src.repositories.business_repo import get_details
from src.repositories.exports_repo import create_export
from src.services.nbp_service import get_nbp_rate
from src.services.ocr_service import OCRExtractionError, RewizorOCRService

logger = logging.getLogger(__name__)
load_dotenv()


__all__ = [
    "BusinessDetailsNotConfigured",
    "process_and_export",
    "cleanup_upload",
]


def _load_business_details(cursor) -> Dict[str, Any]:
    row = get_details(cursor)
    if row is None:
        raise BusinessDetailsNotConfigured(
            "No business_details row configured. POST to "
            "/api/v1/business-details before running an EPP export."
        )
    return row


def process_and_export(file_path: str) -> Dict[str, Any]:
    """Run OCR on *file_path* and return EPP bytes + metadata.

    Raises:
        FileNotFoundError: upload missing.
        OCRExtractionError: OCR failed.
        BusinessDetailsNotConfigured: business_details row missing.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    # Fail-fast: load business details BEFORE spending money on OCR.
    connection = get_connection()
    try:
        cursor = connection.cursor()
        details = _load_business_details(cursor)
    finally:
        cursor.close()
        connection.close()

    info = build_epp_info(details)
    term_days = get_payment_term_days(details)

    try:
        ocr = RewizorOCRService()
    except ValueError as exc:
        logger.error("OCR service init failed: %s", exc)
        raise

    try:
        invoice_data = ocr.extract(file_path)
    except OCRExtractionError:
        logger.error("OCR extraction failed for %s", file_path)
        raise
    except Exception as exc:
        logger.error("Unexpected error during OCR for %s: %s", file_path, exc)
        raise OCRExtractionError(f"OCR failed unexpectedly: {exc}") from exc

    # Classify origin (used for reverse-charge handling in the mapper)
    supplier_type = classify_supplier(invoice_data)
    invoice_data["supplier_region"] = supplier_type["type"]
    invoice_data["supplier_country_code"] = supplier_type.get("code")

    # Replace OCR-reported FX rate with the real NBP mid rate (unless PLN).
    _enrich_fx_rate(invoice_data)

    # Optional: force every extracted date into a specific accounting year.
    # Set ``EPP_FORCE_YEAR`` (e.g. 2027) when Rewizor's open accounting
    # period doesn't cover the dates on the source PDF.
    _apply_year_override(invoice_data)

    try:
        epp_doc = _map_with_term_override(invoice_data, term_days)
        epp_bytes = generate_epp_bytes(info, [epp_doc])
    except Exception as exc:
        logger.error(
            "EPP generation failed for invoice=%s: %s",
            invoice_data.get("invoice_number"), exc,
        )
        raise

    filename = _safe_filename(invoice_data.get("invoice_number") or "export")

    connection = get_connection()
    try:
        cursor = connection.cursor()
        export_row = create_export(
            cursor,
            filename=filename,
            epp_bytes=epp_bytes,
            invoice_data=invoice_data,
            epp_version=info.version,
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        logger.error(
            "Database persistence failed for invoice=%s: %s",
            invoice_data.get("invoice_number"), exc,
        )
        raise
    finally:
        cursor.close()
        connection.close()

    logger.info(
        "Rewizor export (export_id=%s): %s (%d bytes, type=%s)",
        export_row["id"], filename, len(epp_bytes),
        invoice_data.get("doc_type"),
    )
    return {
        "invoice_data": invoice_data,
        "epp_bytes": epp_bytes,
        "epp_filename": filename,
        "doc_type": invoice_data.get("doc_type", "FZ"),
        "export_id": export_row["id"],
        "supplier_region": invoice_data.get("supplier_region"),
        "supplier_country_code": invoice_data.get("supplier_country_code"),
    }


# ── Year override (for accounting-period alignment) ───────────────────────

_DATE_FIELDS = (
    "date",
    "issue_date",
    "sale_date",
    "receipt_date",
    "payment_due_date",
    "corrected_doc_date",
)


def _apply_year_override(invoice_data: Dict[str, Any]) -> None:
    """Rewrite every date field's year to ``EPP_FORCE_YEAR`` when set.

    No-op when the env var is unset or not a valid integer. Preserves the
    month/day so invoice chronology stays intact.
    """
    raw = os.getenv("EPP_FORCE_YEAR")
    if not raw:
        return
    try:
        target_year = int(raw)
    except ValueError:
        logger.warning("Ignoring invalid EPP_FORCE_YEAR=%r", raw)
        return

    for key in _DATE_FIELDS:
        iso = _coerce_iso_date(invoice_data.get(key))
        if not iso:
            continue
        # ISO: YYYY-MM-DD — swap the year prefix
        invoice_data[key] = f"{target_year:04d}{iso[4:]}"

    logger.info("EPP_FORCE_YEAR=%s applied to invoice dates", target_year)


# ── FX rate enrichment ─────────────────────────────────────────────────────

def _enrich_fx_rate(invoice_data: Dict[str, Any]) -> None:
    """Replace a missing/bogus exchange_rate with the real NBP mid rate."""
    currency = (invoice_data.get("currency") or "PLN").strip().upper()
    if currency == "PLN":
        return

    existing_rate = invoice_data.get("exchange_rate")
    needs_lookup = existing_rate is None or existing_rate in (0, 0.0, 1, 1.0)
    if not needs_lookup:
        return

    issue_date = _coerce_iso_date(
        invoice_data.get("date") or invoice_data.get("issue_date")
    )
    if not issue_date:
        logger.warning("Cannot look up NBP rate: no issue_date available")
        return

    rate = get_nbp_rate(currency, issue_date)
    if rate is not None:
        invoice_data["exchange_rate"] = rate
        logger.info(
            "NBP rate for %s on %s: %.4f (replaced OCR value %s)",
            currency, issue_date, rate, existing_rate,
        )
    else:
        logger.warning(
            "NBP rate lookup failed for %s on %s, keeping OCR value %s",
            currency, issue_date, existing_rate,
        )


def _map_with_term_override(
    invoice: Dict[str, Any],
    term_days: Optional[int],
    *,
    doc_type: Optional[str] = None,
) -> EPPDocument:
    """Call the mapper with the configured payment term applied via env var.

    The mapper reads ``EPP_DEFAULT_PAYMENT_TERM_DAYS`` as its fallback; we
    surface the DB-configured value through that env var for the duration
    of the call so the mapper stays unchanged.
    """
    if term_days is None:
        return map_invoice_to_epp(invoice, doc_type=doc_type)

    key = "EPP_DEFAULT_PAYMENT_TERM_DAYS"
    previous = os.environ.get(key)
    os.environ[key] = str(term_days)
    try:
        return map_invoice_to_epp(invoice, doc_type=doc_type)
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


def _safe_filename(base: str) -> str:
    """Sanitise an invoice number into a valid .epp filename."""
    cleaned = base.replace("/", "_").replace("\\", "_").replace(" ", "_")
    cleaned = "".join(c for c in cleaned if c.isalnum() or c in ("_", "-"))
    return (cleaned or "export") + ".epp"


def cleanup_upload(file_path: str) -> None:
    """Remove the uploaded file and any derived images (e.g. *_rewizor.png)."""
    base = file_path.rsplit(".", 1)[0]
    targets = [file_path] + glob.glob(f"{base}_rewizor.*")
    for path in targets:
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.debug("Cleaned up %s", path)
        except OSError as exc:
            logger.warning("Failed to clean up %s: %s", path, exc)
