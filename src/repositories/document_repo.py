"""Database operations for Rewizor documents."""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def insert_document(cursor, document_data: Dict[str, Any]) -> int:
    """Insert an OCR-extracted document into the documents table. Returns document_id."""
    cursor.execute(
        """
        INSERT INTO documents (
            invoice_number, total_amount, currency, vat_amount,
            gross_amount, net_amount, date, vendor, customer,
            contractor_nip, contractor_name,
            contractor_street, contractor_city, contractor_postal_code,
            contractor_country, doc_type, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING document_id
        """,
        (
            document_data.get("invoice_number"),
            document_data.get("total_amount") or document_data.get("gross_amount"),
            document_data.get("currency", "PLN"),
            document_data.get("vat_amount"),
            document_data.get("gross_amount"),
            document_data.get("net_amount"),
            document_data.get("date"),
            document_data.get("vendor"),
            document_data.get("customer"),
            document_data.get("contractor_nip"),
            document_data.get("contractor_name") or document_data.get("vendor"),
            document_data.get("contractor_street"),
            document_data.get("contractor_city"),
            document_data.get("contractor_postal_code"),
            document_data.get("contractor_country"),
            document_data.get("doc_type", "FZ"),
            "PENDING",
        ),
    )
    row = cursor.fetchone()
    return row[0]


def get_documents_by_status(cursor, status: str = "PENDING") -> List[Dict[str, Any]]:
    """Fetch all documents with the given status."""
    cursor.execute(
        """
        SELECT document_id, invoice_number, total_amount, currency,
               vat_amount, gross_amount, net_amount, date, vendor, customer,
               contractor_nip, contractor_name,
               contractor_street, contractor_city, contractor_postal_code,
               contractor_country, doc_type
        FROM documents
        WHERE status = %s
        ORDER BY document_id
        """,
        (status,),
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def get_documents_by_ids(cursor, document_ids: List[int]) -> List[Dict[str, Any]]:
    """Fetch documents by explicit IDs."""
    cursor.execute(
        """
        SELECT document_id, invoice_number, total_amount, currency,
               vat_amount, gross_amount, net_amount, date, vendor, customer,
               contractor_nip, contractor_name,
               contractor_street, contractor_city, contractor_postal_code,
               contractor_country, doc_type
        FROM documents
        WHERE document_id = ANY(%s)
        ORDER BY document_id
        """,
        (document_ids,),
    )
    columns = [desc[0] for desc in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def mark_documents_exported(cursor, document_ids: List[int]) -> int:
    """Mark documents as exported."""
    if not document_ids:
        return 0
    cursor.execute(
        "UPDATE documents SET status = 'EXPORTED' WHERE document_id = ANY(%s)",
        (document_ids,),
    )
    return cursor.rowcount
