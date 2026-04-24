"""Persisted EPP exports — single-table storage.

Every generated ``.epp`` file is stored as ``BYTEA`` in ``exports`` along
with the key invoice metadata (for listing/search) and the raw OCR
payload (for audit). This keeps re-download O(1) and schema-trivial.
"""

import hashlib
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_LIST_COLUMNS = """
    id, filename, file_size, sha256, epp_version,
    invoice_number, doc_type, issue_date, currency,
    net_amount, vat_amount, gross_amount,
    contractor_name, contractor_nip, created_at
"""


def _psycopg2_binary(value: bytes):
    try:
        from psycopg2 import Binary  # type: ignore
    except ImportError:  # pragma: no cover — pure-unit-test env
        return value
    return Binary(value)


def _serialise_ocr(invoice_data: Dict[str, Any]) -> Optional[str]:
    try:
        return json.dumps(
            {k: v for k, v in invoice_data.items() if not isinstance(v, (bytes, bytearray))},
            default=str,
        )
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Failed to serialise ocr_raw for invoice %s: %s",
            invoice_data.get("invoice_number"), exc,
        )
        return None


def create_export(
    cursor,
    *,
    filename: str,
    epp_bytes: bytes,
    invoice_data: Dict[str, Any],
    epp_version: str = "1.12",
) -> Dict[str, Any]:
    """Persist an EPP export + its source invoice snapshot. Returns metadata row (no bytes)."""
    if not epp_bytes:
        raise ValueError("epp_bytes must not be empty")

    sha256 = hashlib.sha256(epp_bytes).hexdigest()
    ocr_raw_json = _serialise_ocr(invoice_data)

    cursor.execute(
        f"""
        INSERT INTO exports (
            filename, epp_bytes, file_size, sha256, epp_version,
            invoice_number, doc_type, issue_date, currency,
            net_amount, vat_amount, gross_amount,
            contractor_name, contractor_nip, ocr_raw
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s::jsonb
        )
        RETURNING {_LIST_COLUMNS}
        """,
        (
            filename,
            _psycopg2_binary(epp_bytes),
            len(epp_bytes),
            sha256,
            epp_version,
            invoice_data.get("invoice_number"),
            invoice_data.get("doc_type", "FZ"),
            invoice_data.get("issue_date") or invoice_data.get("date"),
            invoice_data.get("currency", "PLN"),
            invoice_data.get("net_amount"),
            invoice_data.get("vat_amount"),
            invoice_data.get("gross_amount"),
            invoice_data.get("contractor_name") or invoice_data.get("vendor"),
            invoice_data.get("contractor_nip"),
            ocr_raw_json,
        ),
    )
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, cursor.fetchone()))


def get_export_metadata(cursor, export_id: int) -> Optional[Dict[str, Any]]:
    cursor.execute(
        f"SELECT {_LIST_COLUMNS} FROM exports WHERE id = %s",
        (export_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def get_export_bytes(cursor, export_id: int) -> Optional[Dict[str, Any]]:
    """Fetch the export bytes + filename for re-download."""
    cursor.execute(
        """
        SELECT id, filename, epp_bytes, file_size, sha256
        FROM exports
        WHERE id = %s
        """,
        (export_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    record = dict(zip(columns, row))
    if isinstance(record.get("epp_bytes"), memoryview):
        record["epp_bytes"] = bytes(record["epp_bytes"])
    return record


def list_exports(
    cursor,
    *,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    cursor.execute(
        f"""
        SELECT {_LIST_COLUMNS}
        FROM exports
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        (limit, offset),
    )
    columns = [d[0] for d in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def count_exports(cursor) -> int:
    cursor.execute("SELECT COUNT(*) FROM exports")
    return int(cursor.fetchone()[0])
