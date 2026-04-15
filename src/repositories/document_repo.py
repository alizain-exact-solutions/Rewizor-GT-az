"""Database operations for Rewizor documents — tenant-scoped.

Persists every field the OCR can extract, plus the per-rate VAT
breakdown in a child table. Every query is scoped by ``tenant_id`` so
documents cannot leak between businesses.
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# Columns selected by the listing/detail endpoints. Kept as a constant so
# every read returns the same projection and the API schema stays in sync.
_DOCUMENT_COLUMNS = """
    document_id, tenant_id, invoice_number, doc_type, status,
    is_correction, corrected_doc_number, corrected_doc_date,
    issue_date, sale_date, receipt_date, payment_due_date,
    currency, exchange_rate, net_amount, vat_amount, gross_amount,
    total_amount, amount_paid, payment_method,
    vendor, customer, contractor_nip, contractor_name,
    contractor_street, contractor_city, contractor_postal_code,
    contractor_region, contractor_country, customer_nip,
    supplier_region, supplier_country_code,
    transaction_id, notes, created_at, updated_at
"""


def insert_document(
    cursor, document_data: Dict[str, Any], *, tenant_id: str
) -> int:
    """Insert a document for *tenant_id* and return its ``document_id``.

    Persists every OCR-extracted scalar field, plus the per-rate VAT
    breakdown into ``document_vat_lines`` (one row per rate). The full
    OCR payload is stashed in ``ocr_raw`` (JSONB) as an audit trail.
    """
    issue_date = document_data.get("issue_date") or document_data.get("date")
    gross = document_data.get("gross_amount")
    total = document_data.get("total_amount") or gross

    # JSONB needs proper serialisation — drop bytes and other non-JSON values
    # so the audit copy can never break the insert.
    try:
        ocr_raw_json = json.dumps(
            {k: v for k, v in document_data.items() if not isinstance(v, (bytes, bytearray))},
            default=str,
        )
    except (TypeError, ValueError) as exc:
        logger.warning("Failed to serialise ocr_raw for invoice %s: %s",
                       document_data.get("invoice_number"), exc)
        ocr_raw_json = None

    cursor.execute(
        """
        INSERT INTO documents (
            tenant_id,
            invoice_number, doc_type, status,
            is_correction, corrected_doc_number, corrected_doc_date,
            date, issue_date, sale_date, receipt_date, payment_due_date,
            currency, exchange_rate,
            net_amount, vat_amount, gross_amount, total_amount, amount_paid,
            payment_method,
            vendor, customer,
            contractor_nip, contractor_name,
            contractor_street, contractor_city, contractor_postal_code,
            contractor_region, contractor_country,
            customer_nip,
            supplier_region, supplier_country_code,
            transaction_id, notes, ocr_raw
        )
        VALUES (
            %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s,
            %s, %s, %s, %s, %s,
            %s,
            %s, %s,
            %s, %s,
            %s, %s, %s,
            %s, %s,
            %s,
            %s, %s,
            %s, %s, %s::jsonb
        )
        RETURNING document_id
        """,
        (
            tenant_id,
            document_data.get("invoice_number"),
            document_data.get("doc_type", "FZ"),
            document_data.get("status", "PENDING"),
            bool(document_data.get("is_correction", False)),
            document_data.get("corrected_doc_number"),
            document_data.get("corrected_doc_date"),
            issue_date, issue_date,
            document_data.get("sale_date") or issue_date,
            document_data.get("receipt_date") or issue_date,
            document_data.get("payment_due_date"),
            document_data.get("currency", "PLN"),
            document_data.get("exchange_rate"),
            document_data.get("net_amount"),
            document_data.get("vat_amount"),
            gross,
            total,
            document_data.get("amount_paid"),
            document_data.get("payment_method"),
            document_data.get("vendor"),
            document_data.get("customer"),
            document_data.get("contractor_nip"),
            document_data.get("contractor_name") or document_data.get("vendor"),
            document_data.get("contractor_street"),
            document_data.get("contractor_city"),
            document_data.get("contractor_postal_code"),
            document_data.get("contractor_region"),
            document_data.get("contractor_country"),
            document_data.get("customer_nip"),
            document_data.get("supplier_region"),
            document_data.get("supplier_country_code"),
            document_data.get("transaction_id"),
            document_data.get("notes"),
            ocr_raw_json,
        ),
    )
    document_id: int = cursor.fetchone()[0]

    # ── Per-rate VAT breakdown ──
    breakdown = document_data.get("vat_breakdown") or []
    if isinstance(breakdown, list):
        for line_no, row in enumerate(breakdown, start=1):
            if not isinstance(row, dict):
                continue
            cursor.execute(
                """
                INSERT INTO document_vat_lines (
                    document_id, line_no, vat_symbol, vat_rate,
                    net_amount, vat_amount, gross_amount
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    document_id,
                    line_no,
                    str(row.get("symbol") or row.get("vat_symbol") or "23"),
                    row.get("rate") or row.get("vat_rate") or 0,
                    row.get("net") or row.get("net_amount") or 0,
                    row.get("vat") or row.get("vat_amount") or 0,
                    row.get("gross") or row.get("gross_amount") or 0,
                ),
            )

    return document_id


def get_document(cursor, document_id: int, *, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return one document (with its VAT lines) for *tenant_id* or ``None``."""
    cursor.execute(
        f"""
        SELECT {_DOCUMENT_COLUMNS}
        FROM documents
        WHERE tenant_id = %s AND document_id = %s
        """,
        (tenant_id, document_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    document = dict(zip(columns, row))
    document["vat_breakdown"] = _fetch_vat_lines(cursor, document_id)
    return document


def list_documents(
    cursor,
    *,
    tenant_id: str,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List documents for *tenant_id* with optional filters and pagination.

    VAT breakdown is **not** included to keep listings cheap; call
    :func:`get_document` for the full record.
    """
    where = ["tenant_id = %s"]
    params: List[Any] = [tenant_id]
    if status:
        where.append("status = %s")
        params.append(status)
    if doc_type:
        where.append("doc_type = %s")
        params.append(doc_type)

    sql = f"""
        SELECT {_DOCUMENT_COLUMNS}
        FROM documents
        WHERE {' AND '.join(where)}
        ORDER BY document_id DESC
        LIMIT %s OFFSET %s
    """
    params.extend([max(1, min(limit, 500)), max(0, offset)])

    cursor.execute(sql, params)
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def count_documents(
    cursor,
    *,
    tenant_id: str,
    status: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> int:
    """Total count for the same filter set used by :func:`list_documents`."""
    where = ["tenant_id = %s"]
    params: List[Any] = [tenant_id]
    if status:
        where.append("status = %s")
        params.append(status)
    if doc_type:
        where.append("doc_type = %s")
        params.append(doc_type)

    cursor.execute(
        f"SELECT COUNT(*) FROM documents WHERE {' AND '.join(where)}",
        params,
    )
    return int(cursor.fetchone()[0])


def get_documents_by_status(
    cursor, status: str = "PENDING", *, tenant_id: str
) -> List[Dict[str, Any]]:
    """Fetch all documents with the given status for *tenant_id*."""
    return list_documents(cursor, tenant_id=tenant_id, status=status, limit=500)


def get_documents_by_ids(
    cursor, document_ids: List[int], *, tenant_id: str
) -> List[Dict[str, Any]]:
    """Fetch documents by explicit IDs, restricted to *tenant_id*."""
    if not document_ids:
        return []
    cursor.execute(
        f"""
        SELECT {_DOCUMENT_COLUMNS}
        FROM documents
        WHERE tenant_id = %s AND document_id = ANY(%s)
        ORDER BY document_id
        """,
        (tenant_id, document_ids),
    )
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def mark_documents_exported(
    cursor, document_ids: List[int], *, tenant_id: str
) -> int:
    """Mark documents as exported (tenant-scoped)."""
    if not document_ids:
        return 0
    cursor.execute(
        """
        UPDATE documents
        SET status = 'EXPORTED', updated_at = NOW()
        WHERE tenant_id = %s AND document_id = ANY(%s)
        """,
        (tenant_id, document_ids),
    )
    return cursor.rowcount


# ── Helpers ────────────────────────────────────────────────────────────────

def _fetch_vat_lines(cursor, document_id: int) -> List[Dict[str, Any]]:
    cursor.execute(
        """
        SELECT line_no, vat_symbol, vat_rate, net_amount, vat_amount, gross_amount
        FROM document_vat_lines
        WHERE document_id = %s
        ORDER BY line_no
        """,
        (document_id,),
    )
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]
