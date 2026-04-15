"""Persisted EPP exports — tenant-scoped storage and retrieval.

Every generated ``.epp`` file is stored as ``BYTEA`` in
``document_exports``, joined to the source documents through
``export_documents``. This lets the user re-download the exact bytes
they originally received without regeneration drift (which would
otherwise happen if the tenant's accounting settings change between
exports).
"""

import hashlib
import logging
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


_EXPORT_COLUMNS_NO_BYTES = """
    export_id, tenant_id, filename, file_size, sha256, epp_version,
    doc_count, export_kind, created_at
"""


def create_export(
    cursor,
    *,
    tenant_id: str,
    filename: str,
    epp_bytes: bytes,
    document_ids: Sequence[int],
    epp_version: str = "1.12",
    export_kind: str = "single",
) -> Dict[str, Any]:
    """Persist an EPP export. Returns the metadata row (no bytes)."""
    if not epp_bytes:
        raise ValueError("epp_bytes must not be empty")
    if not document_ids:
        raise ValueError("document_ids must contain at least one id")

    sha256 = hashlib.sha256(epp_bytes).hexdigest()

    cursor.execute(
        f"""
        INSERT INTO document_exports (
            tenant_id, filename, epp_bytes, file_size, sha256,
            epp_version, doc_count, export_kind
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING {_EXPORT_COLUMNS_NO_BYTES}
        """,
        (
            tenant_id,
            filename,
            psycopg2_binary(epp_bytes),
            len(epp_bytes),
            sha256,
            epp_version,
            len(document_ids),
            export_kind,
        ),
    )
    columns = [d[0] for d in cursor.description]
    export_row = dict(zip(columns, cursor.fetchone()))

    # Link the export to its source documents (m2m).
    cursor.executemany(
        "INSERT INTO export_documents (export_id, document_id) VALUES (%s, %s)",
        [(export_row["export_id"], doc_id) for doc_id in document_ids],
    )

    return export_row


def get_export_metadata(
    cursor, export_id: int, *, tenant_id: str
) -> Optional[Dict[str, Any]]:
    """Fetch the export's metadata (no bytes) — returns ``None`` if absent."""
    cursor.execute(
        f"""
        SELECT {_EXPORT_COLUMNS_NO_BYTES}
        FROM document_exports
        WHERE tenant_id = %s AND export_id = %s
        """,
        (tenant_id, export_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    metadata = dict(zip(columns, row))

    # Attach the IDs of the documents this export covers (cheap, indexed).
    cursor.execute(
        "SELECT document_id FROM export_documents WHERE export_id = %s ORDER BY document_id",
        (export_id,),
    )
    metadata["document_ids"] = [r[0] for r in cursor.fetchall()]
    return metadata


def get_export_bytes(
    cursor, export_id: int, *, tenant_id: str
) -> Optional[Dict[str, Any]]:
    """Fetch the export bytes + filename for re-download. Tenant-scoped."""
    cursor.execute(
        """
        SELECT export_id, filename, epp_bytes, file_size, sha256
        FROM document_exports
        WHERE tenant_id = %s AND export_id = %s
        """,
        (tenant_id, export_id),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    record = dict(zip(columns, row))
    # psycopg2 hands BYTEA back as ``memoryview``; normalise to bytes for
    # JSON-serialisable APIs and predictable hashing on the way back out.
    if isinstance(record.get("epp_bytes"), memoryview):
        record["epp_bytes"] = bytes(record["epp_bytes"])
    return record


def list_exports(
    cursor,
    *,
    tenant_id: str,
    document_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List exports for *tenant_id*, optionally filtered by source document.

    Returns metadata rows (no bytes), newest first. Each row carries the
    list of source ``document_ids`` so the frontend can render "this
    export covers documents 12, 13, 14".
    """
    limit = max(1, min(limit, 500))
    offset = max(0, offset)

    if document_id is not None:
        cursor.execute(
            f"""
            SELECT {_EXPORT_COLUMNS_NO_BYTES}
            FROM document_exports e
            WHERE e.tenant_id = %s
              AND EXISTS (
                  SELECT 1 FROM export_documents ed
                  WHERE ed.export_id = e.export_id AND ed.document_id = %s
              )
            ORDER BY e.created_at DESC, e.export_id DESC
            LIMIT %s OFFSET %s
            """,
            (tenant_id, document_id, limit, offset),
        )
    else:
        cursor.execute(
            f"""
            SELECT {_EXPORT_COLUMNS_NO_BYTES}
            FROM document_exports
            WHERE tenant_id = %s
            ORDER BY created_at DESC, export_id DESC
            LIMIT %s OFFSET %s
            """,
            (tenant_id, limit, offset),
        )

    columns = [d[0] for d in cursor.description]
    rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

    # Attach document_ids in a single follow-up query (avoids N+1).
    if rows:
        export_ids = [r["export_id"] for r in rows]
        cursor.execute(
            """
            SELECT export_id, document_id
            FROM export_documents
            WHERE export_id = ANY(%s)
            ORDER BY export_id, document_id
            """,
            (export_ids,),
        )
        by_export: Dict[int, List[int]] = {eid: [] for eid in export_ids}
        for export_id, doc_id in cursor.fetchall():
            by_export[export_id].append(doc_id)
        for r in rows:
            r["document_ids"] = by_export.get(r["export_id"], [])

    return rows


def count_exports(
    cursor, *, tenant_id: str, document_id: Optional[int] = None
) -> int:
    """Total exports for *tenant_id*, optionally filtered by document."""
    if document_id is not None:
        cursor.execute(
            """
            SELECT COUNT(*) FROM document_exports e
            WHERE e.tenant_id = %s
              AND EXISTS (
                  SELECT 1 FROM export_documents ed
                  WHERE ed.export_id = e.export_id AND ed.document_id = %s
              )
            """,
            (tenant_id, document_id),
        )
    else:
        cursor.execute(
            "SELECT COUNT(*) FROM document_exports WHERE tenant_id = %s",
            (tenant_id,),
        )
    return int(cursor.fetchone()[0])


# ── Helpers ────────────────────────────────────────────────────────────────

def psycopg2_binary(value: bytes):
    """Wrap raw bytes in psycopg2's Binary adapter when the driver is loaded.

    Falls back to the raw bytes object when psycopg2 is unavailable (used
    in unit tests against a fake cursor — they don't care).
    """
    try:
        from psycopg2 import Binary  # type: ignore
    except ImportError:  # pragma: no cover — only in pure-unit-test envs
        return value
    return Binary(value)
