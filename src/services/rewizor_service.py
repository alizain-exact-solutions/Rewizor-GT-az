"""
Rewizor GT export service – orchestrator.

Two main workflows:

1. **OCR + Export**  (``process_and_export``)
   Upload PDF → Rewizor OCR → EPP file bytes. Also persists the document
   and the generated export so they can be fetched later.

2. **Regenerate**  (``regenerate_export``)
   Load a persisted document → re-map with the tenant's *current*
   accounting settings → EPP file bytes. A fresh export row is stored.

Both workflows are **tenant-scoped**. The caller supplies a ``tenant_id``
and the service loads that tenant's accounting settings from the database
to build the EPP [INFO] section. Settings are managed by the frontend via
``/api/v1/accounting/settings``; if no row exists for the tenant we raise
:class:`AccountingNotConfigured` so the caller can return a useful error.
"""

import glob
import logging
import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv

from src.core.db import db_session, get_connection
from src.epp.classifier import classify_supplier
from src.epp.epp_writer import generate_epp_bytes
from src.epp.mapper import _coerce_iso_date, map_invoice_to_epp
from src.epp.schemas import EPPInfo
from src.repositories.accounting_repo import get_settings as get_accounting_settings
from src.repositories.document_repo import (
    get_document,
    insert_document,
)
from src.repositories.exports_repo import create_export
from src.services.nbp_service import get_nbp_rate
from src.services.ocr_service import OCRExtractionError, RewizorOCRService

logger = logging.getLogger(__name__)
load_dotenv()


class AccountingNotConfigured(Exception):
    """Raised when the tenant has not yet saved their accounting details.

    The API layer should translate this to a user-visible 409/412 prompting
    the frontend to send the operator to the Accounting Details page.
    """


# ── Accounting settings → EPPInfo ─────────────────────────────────────────

def _build_epp_info(tenant_id: str) -> EPPInfo:
    """Load the tenant's accounting settings and build the EPP [INFO] header.

    Raises :class:`AccountingNotConfigured` when the tenant has no row in
    ``accounting_settings`` — the frontend must collect the details before
    export is possible.
    """
    with db_session() as conn:
        cursor = conn.cursor()
        settings = get_accounting_settings(cursor, tenant_id)
        cursor.close()

    if settings is None:
        raise AccountingNotConfigured(
            f"Tenant '{tenant_id}' has no accounting_settings row. "
            "The frontend must save the Accounting Details form first."
        )

    nip = (settings.get("company_nip") or "").strip().upper()
    if nip.startswith("PL"):
        nip = nip[2:]

    return EPPInfo(
        producing_program=settings.get("producing_program") or "Subiekt GT",
        sender_id_code=settings.get("sender_id_code") or "",
        sender_short_name=settings.get("sender_short_name") or "",
        sender_long_name=settings.get("company_name") or "",
        sender_city=settings.get("company_city") or "",
        sender_postal_code=settings.get("company_postal_code") or "",
        sender_street=settings.get("company_street") or "",
        sender_nip=nip,
        warehouse_code=settings.get("warehouse_code") or "MAG",
        warehouse_name=settings.get("warehouse_name") or "Główny",
        warehouse_description=settings.get("warehouse_description") or "Magazyn główny",
        operator_name=settings.get("operator_name") or "Szef",
        country_prefix=(settings.get("company_country_code") or "PL").upper(),
        # Field 23 — working Subiekt GT exports emit the bare NIP here.
        eu_vat_number=nip,
        is_sender_eu=0,
    )


def _resolve_payment_term_days(tenant_id: str) -> Optional[int]:
    """Return the tenant's configured default payment term, or ``None``.

    The mapper checks ``EPP_DEFAULT_PAYMENT_TERM_DAYS`` — we surface the
    per-tenant value through that env var for the duration of each call so
    tenants with different terms don't contaminate each other.
    """
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            settings = get_accounting_settings(cursor, tenant_id)
            cursor.close()
    except Exception:
        return None
    if settings is None:
        return None
    days = settings.get("default_payment_term_days")
    try:
        return int(days) if days is not None else None
    except (TypeError, ValueError):
        return None


# ── Workflow 1: OCR + immediate export ───────────────────────────────────────

def process_and_export(file_path: str, *, tenant_id: str) -> Dict[str, Any]:
    """Run OCR on *file_path* and return EPP bytes + extracted data for *tenant_id*.

    The document is persisted to the database tagged with the tenant id so
    it can be regenerated later via :func:`regenerate_export`.

    Returns::

        {
            "invoice_data": { … },
            "epp_bytes": b"…",
            "epp_filename": "FV_001_2026.epp",
            "doc_type": "FZ",
            "document_id": 42,
            "supplier_region": "EU",
            "supplier_country_code": "NL",
        }

    Raises:
        FileNotFoundError: upload missing.
        OCRExtractionError: OCR failed.
        AccountingNotConfigured: tenant has no saved settings yet.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    # Fail-fast: check tenant config BEFORE spending money on OCR.
    info = _build_epp_info(tenant_id)
    term_days = _resolve_payment_term_days(tenant_id)

    # ── OCR extraction ──
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

    # ── NBP exchange rate lookup ──
    # For foreign-currency invoices, fetch the real NBP rate instead of
    # relying on whatever the OCR returned (often null or 1.0).
    _enrich_fx_rate(invoice_data)

    # ── Map to EPP and generate file ──
    try:
        epp_doc = _map_with_term_override(invoice_data, term_days)
        epp_bytes = generate_epp_bytes(info, [epp_doc])
    except Exception as exc:
        logger.error(
            "EPP generation failed for tenant=%s invoice=%s: %s",
            tenant_id, invoice_data.get("invoice_number"), exc,
        )
        raise

    filename = _safe_filename(invoice_data.get("invoice_number") or "export")

    # ── Persist document, VAT lines, and the EPP export atomically ──
    connection = get_connection()
    try:
        cursor = connection.cursor()
        document_id = insert_document(cursor, invoice_data, tenant_id=tenant_id)
        export_row = create_export(
            cursor,
            tenant_id=tenant_id,
            filename=filename,
            epp_bytes=epp_bytes,
            document_ids=[document_id],
            epp_version=info.version,
            export_kind="single",
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        logger.error(
            "Database persistence failed for tenant=%s invoice=%s: %s",
            tenant_id, invoice_data.get("invoice_number"), exc,
        )
        raise
    finally:
        cursor.close()
        connection.close()

    logger.info(
        "Rewizor export (tenant=%s, document_id=%s, export_id=%s): %s (%d bytes, type=%s)",
        tenant_id, document_id, export_row["export_id"],
        filename, len(epp_bytes), invoice_data.get("doc_type"),
    )
    return {
        "invoice_data": invoice_data,
        "epp_bytes": epp_bytes,
        "epp_filename": filename,
        "doc_type": invoice_data.get("doc_type", "FZ"),
        "document_id": document_id,
        "export_id": export_row["export_id"],
        "supplier_region": invoice_data.get("supplier_region"),
        "supplier_country_code": invoice_data.get("supplier_country_code"),
    }


# ── Workflow 2: regenerate from a stored document ────────────────────────

def regenerate_export(
    *, tenant_id: str, document_id: int
) -> Dict[str, Any]:
    """Regenerate a fresh EPP from a stored document and persist a new export.

    This honours the tenant's *current* accounting settings, so it's the
    right call when settings have changed since the original export.
    Returns the new export's metadata + bytes.
    """
    info = _build_epp_info(tenant_id)
    term_days = _resolve_payment_term_days(tenant_id)

    connection = get_connection()
    try:
        cursor = connection.cursor()
        document = get_document(cursor, document_id, tenant_id=tenant_id)
        if document is None:
            raise LookupError(
                f"Document {document_id} not found for tenant {tenant_id}"
            )

        _enrich_fx_rate(document)
        epp_doc = _map_with_term_override(document, term_days)
        epp_bytes = generate_epp_bytes(info, [epp_doc])
        filename = _safe_filename(
            document.get("invoice_number") or f"document_{document_id}"
        )

        export_row = create_export(
            cursor,
            tenant_id=tenant_id,
            filename=filename,
            epp_bytes=epp_bytes,
            document_ids=[document_id],
            epp_version=info.version,
            export_kind="regenerated",
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    logger.info(
        "Rewizor regenerate (tenant=%s, document_id=%s, export_id=%s): %s (%d bytes)",
        tenant_id, document_id, export_row["export_id"],
        filename, len(epp_bytes),
    )
    return {
        "epp_bytes": epp_bytes,
        "epp_filename": filename,
        "export_id": export_row["export_id"],
        "document_id": document_id,
    }


# Re-export so the API layer can `from src.services.rewizor_service import …`
__all__ = [
    "AccountingNotConfigured",
    "process_and_export",
    "regenerate_export",
    "cleanup_upload",
]


# ── FX rate enrichment ─────────────────────────────────────────────────────

def _enrich_fx_rate(invoice_data: Dict[str, Any]) -> None:
    """Replace a missing/bogus exchange_rate with the real NBP mid rate.

    Called after OCR and before the mapper.  Leaves PLN invoices untouched.
    If the NBP lookup fails we keep whatever the OCR returned so the
    pipeline still works (the mapper already logs a warning for rate=1.0).
    """
    currency = (invoice_data.get("currency") or "PLN").strip().upper()
    if currency == "PLN":
        return

    existing_rate = invoice_data.get("exchange_rate")
    # Treat 0, 1.0 (the mapper's fallback), and None as "we don't have a real rate"
    needs_lookup = existing_rate is None or existing_rate in (0, 0.0, 1, 1.0)

    if not needs_lookup:
        return

    # Issue date may arrive as a ``datetime.date`` (psycopg2 DATE column) or
    # a string (OCR output); coerce to ISO so NBP's strptime/strip works.
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


# ── Helpers ──────────────────────────────────────────────────────────────────

def _map_with_term_override(
    invoice: Dict[str, Any],
    term_days: Optional[int],
    *,
    doc_type: Optional[str] = None,
) -> EPPDocument:
    """Call the mapper with the tenant's configured payment term applied.

    The mapper reads ``EPP_DEFAULT_PAYMENT_TERM_DAYS`` from the environment
    as its fallback. To honour the per-tenant value without refactoring
    the mapper signature, we set the env var for the duration of the call
    and restore it afterwards.
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
