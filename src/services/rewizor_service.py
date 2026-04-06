"""
Rewizor GT export service – orchestrator.

Two main workflows:

1. **OCR + Export**  (``process_and_export``)
   Upload PDF → Rewizor OCR → EPP file bytes

2. **DB Export**  (``export_from_db``)
   Fetch documents already in the database → EPP file bytes
"""

import glob
import logging
import os
from typing import Any, Dict, List, Optional

import psycopg2
from dotenv import load_dotenv

from src.epp.constants import DOC_TYPE_PURCHASE_INVOICE
from src.epp.classifier import classify_supplier
from src.epp.epp_writer import generate_epp_bytes
from src.epp.mapper import map_invoice_to_epp
from src.epp.schemas import EPPDocument, EPPInfo
from src.repositories.document_repo import insert_document, mark_documents_exported
from src.services.ocr_service import OCRExtractionError, RewizorOCRService

logger = logging.getLogger(__name__)
load_dotenv()


def _get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def _build_epp_info() -> EPPInfo:
    """Read sender / accounting-office details from environment.

    The [INFO] section always reflects the **importer's own company**
    (the Rewizor user), never the invoice buyer.  Configure via env vars:
    ``EPP_COMPANY_NAME``, ``EPP_COMPANY_NIP``, etc.
    """
    return EPPInfo(
        generator_name=os.getenv("EPP_SENDER_NAME", "ExactFlow Finance"),
        generator_nip=os.getenv("EPP_SENDER_NIP", ""),
        generator_city=os.getenv("EPP_SENDER_CITY", ""),
        company_name=os.getenv("EPP_COMPANY_NAME", ""),
        company_nip=os.getenv("EPP_COMPANY_NIP", ""),
        company_street=os.getenv("EPP_COMPANY_STREET", ""),
        company_city=os.getenv("EPP_COMPANY_CITY", ""),
        company_postal_code=os.getenv("EPP_COMPANY_POSTAL_CODE", ""),
    )


# ── Workflow 1: OCR + immediate export ───────────────────────────────────────

def process_and_export(
    file_path: str,
) -> Dict[str, Any]:
    """Run Rewizor OCR on *file_path* and return EPP bytes + extracted data.

    The document type (FZ, FS, KZ, KS, FZK, FSK, KZK, KSK, WB, RK, PK, DE)
    is auto-detected by the OCR from the document content.

    Returns::

        {
            "invoice_data": { … },
            "epp_bytes": b"…",
            "epp_filename": "FV_001_2026.epp",
            "doc_type": "FS",
        }
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Document file not found: {file_path}")

    # ── Step 1: OCR extraction ──────────────────────────────────────────
    try:
        ocr = RewizorOCRService()
    except ValueError as exc:
        logger.error("OCR service init failed (missing API key?): %s", exc)
        raise

    try:
        invoice_data = ocr.extract(file_path)
    except OCRExtractionError:
        logger.error("OCR extraction failed for %s", file_path)
        raise
    except Exception as exc:
        logger.error("Unexpected error during OCR for %s: %s", file_path, exc)
        raise OCRExtractionError(f"OCR failed unexpectedly: {exc}") from exc

    # ── Step 1b: Classify supplier origin ────────────────────────────────
    supplier_type = classify_supplier(invoice_data)
    invoice_data["supplier_region"] = supplier_type["type"]
    invoice_data["supplier_country_code"] = supplier_type.get("code")

    # ── Step 2: Persist to database ─────────────────────────────────────
    connection = _get_db_connection()
    try:
        cursor = connection.cursor()
        document_id = insert_document(cursor, invoice_data)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        logger.error("Database insert failed for invoice %s: %s",
                      invoice_data.get("invoice_number"), exc)
        raise
    finally:
        cursor.close()
        connection.close()

    # ── Step 3: Map to EPP and generate file ────────────────────────────
    try:
        epp_doc = map_invoice_to_epp(invoice_data)
        info = _build_epp_info()
        epp_bytes = generate_epp_bytes(info, [epp_doc])
    except Exception as exc:
        logger.error("EPP generation failed for invoice %s: %s",
                      invoice_data.get("invoice_number"), exc)
        raise

    filename = _safe_filename(invoice_data.get("invoice_number") or "export")

    logger.info(
        "Rewizor export: generated %s (%d bytes, type=%s)",
        filename, len(epp_bytes), invoice_data.get("doc_type"),
    )
    return {
        "invoice_data": invoice_data,
        "epp_bytes": epp_bytes,
        "epp_filename": filename,
        "doc_type": invoice_data.get("doc_type", "FZ"),
        "document_id": document_id,
        "supplier_region": invoice_data.get("supplier_region"),
        "supplier_country_code": invoice_data.get("supplier_country_code"),
    }


# ── Workflow 2: batch export from DB ─────────────────────────────────────────

def export_from_db(
    *,
    document_ids: Optional[List[int]] = None,
    status: str = "PENDING",
    doc_type: str = DOC_TYPE_PURCHASE_INVOICE,
) -> Dict[str, Any]:
    """Fetch documents from the database and generate a batch EPP file.

    Args:
        document_ids: Explicit list of ``document_id`` values. When *None*,
                      all documents matching *status* are exported.
        status: Document status filter (used when *document_ids* is None).
        doc_type: Document type written into [NAGLOWEK].

    Returns::

        {
            "count": int,
            "epp_bytes": b"…",
            "epp_filename": "rewizor_export.epp",
        }
    """
    try:
        connection = _get_db_connection()
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
        raise

    try:
        cursor = connection.cursor()

        if document_ids:
            cursor.execute(
                """
                SELECT document_id, invoice_number, total_amount, currency,
                       vat_amount, gross_amount, net_amount, date,
                       vendor, customer, contractor_nip, contractor_name,
                       contractor_street, contractor_city, contractor_postal_code,
                       contractor_country, supplier_region, supplier_country_code,
                       doc_type
                FROM documents
                WHERE document_id = ANY(%s)
                ORDER BY document_id
                """,
                (document_ids,),
            )
        else:
            cursor.execute(
                """
                SELECT document_id, invoice_number, total_amount, currency,
                       vat_amount, gross_amount, net_amount, date,
                       vendor, customer, contractor_nip, contractor_name,
                       contractor_street, contractor_city, contractor_postal_code,
                       contractor_country, supplier_region, supplier_country_code,
                       doc_type
                FROM documents
                WHERE status = %s
                ORDER BY document_id
                """,
                (status,),
            )

        columns = [desc[0] for desc in cursor.description]
        rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        if not rows:
            logger.warning("Rewizor export: no documents found (status=%s, ids=%s)",
                           status, document_ids)
            return {"count": 0, "epp_bytes": b"", "epp_filename": ""}

        # Map each DB row to an EPP document
        documents: List[EPPDocument] = []
        for row in rows:
            try:
                epp_doc = map_invoice_to_epp(row, doc_type=row.get("doc_type") or doc_type)
                documents.append(epp_doc)
            except Exception as exc:
                logger.error("EPP mapping failed for document_id=%s: %s",
                             row.get("document_id"), exc)
                raise

        info = _build_epp_info()
        epp_bytes = generate_epp_bytes(info, documents)
        filename = _safe_filename("rewizor_export")

        exported_ids = [row["document_id"] for row in rows]
        mark_documents_exported(cursor, exported_ids)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    logger.info(
        "Rewizor DB export: %d document(s), %d bytes", len(documents), len(epp_bytes)
    )
    return {
        "count": len(documents),
        "epp_bytes": epp_bytes,
        "epp_filename": filename,
    }


# ── Helpers ──────────────────────────────────────────────────────────────────

def _safe_filename(base: str) -> str:
    """Sanitise an invoice number into a valid .epp filename."""
    cleaned = base.replace("/", "_").replace("\\", "_").replace(" ", "_")
    cleaned = "".join(c for c in cleaned if c.isalnum() or c in ("_", "-"))
    return (cleaned or "export") + ".epp"


def cleanup_upload(file_path: str) -> None:
    """Remove the uploaded file and any derived images (e.g. *_rewizor.png).

    Silently ignores missing files so callers can fire-and-forget.
    """
    base = file_path.rsplit(".", 1)[0]
    targets = [file_path] + glob.glob(f"{base}_rewizor.*")
    for path in targets:
        try:
            if os.path.isfile(path):
                os.remove(path)
                logger.debug("Cleaned up %s", path)
        except OSError as exc:
            logger.warning("Failed to clean up %s: %s", path, exc)
    
    
    
    
    
    
    
    