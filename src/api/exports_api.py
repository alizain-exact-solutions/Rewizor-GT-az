"""Stored EPP export endpoints — list, metadata, and re-download.

Every generated ``.epp`` file is persisted in ``document_exports`` so the
user can re-download the exact bytes at any point — no risk of the file
silently changing because the tenant's accounting settings were edited
in the meantime.

Three endpoints:

* ``GET  /exports``                 — paginated listing (no bytes).
* ``GET  /exports/{export_id}``     — metadata for one export.
* ``GET  /exports/{export_id}/download`` — the actual ``.epp`` bytes.

Every query is tenant-scoped at the repository layer.
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.schemas import ExportListResponse, ExportSummary
from src.api.tenant import get_tenant_id
from src.core.db import db_session
from src.repositories.exports_repo import (
    count_exports,
    get_export_bytes,
    get_export_metadata,
    list_exports,
)

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/exports", tags=["exports"])


# ── List ──────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=ExportListResponse,
    summary="List stored EPP exports for the current tenant",
)
@limiter.limit("60/minute")
async def list_exports_endpoint(
    request: Request,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    document_id: Optional[int] = Query(
        None,
        description="Filter to exports that include this source document.",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated listing of stored exports — metadata only, no bytes.

    Bytes live behind ``/exports/{export_id}/download`` so the listing
    stays cheap to fetch and render.
    """
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            rows = list_exports(
                cursor,
                tenant_id=tenant_id,
                document_id=document_id,
                limit=limit,
                offset=offset,
            )
            total = count_exports(
                cursor, tenant_id=tenant_id, document_id=document_id
            )
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to list exports for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    return ExportListResponse(
        items=[ExportSummary(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Metadata ──────────────────────────────────────────────────────────────

@router.get(
    "/{export_id}",
    response_model=ExportSummary,
    summary="Get metadata for a stored EPP export",
    responses={404: {"description": "Export not found for this tenant."}},
)
@limiter.limit("120/minute")
async def read_export(
    request: Request,
    export_id: int,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Return metadata (no bytes) for a single stored export."""
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            metadata = get_export_metadata(cursor, export_id, tenant_id=tenant_id)
            cursor.close()
    except Exception as exc:
        logger.exception(
            "Failed to load export %s for tenant %s", export_id, tenant_id
        )
        raise HTTPException(status_code=500, detail="Database error") from exc

    if metadata is None:
        raise HTTPException(
            status_code=404, detail=f"Export {export_id} not found."
        )
    return ExportSummary(**metadata)


# ── Download bytes ────────────────────────────────────────────────────────

@router.get(
    "/{export_id}/download",
    summary="Download the stored .epp bytes for an export",
    response_class=Response,
    responses={404: {"description": "Export not found for this tenant."}},
)
@limiter.limit("30/minute")
async def download_export(
    request: Request,
    export_id: int,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Return the stored ``.epp`` bytes (``application/octet-stream``).

    Uses the exact bytes that were originally generated — no regeneration
    drift if the tenant's accounting settings have since changed.
    """
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            record = get_export_bytes(cursor, export_id, tenant_id=tenant_id)
            cursor.close()
    except Exception as exc:
        logger.exception(
            "Failed to fetch export bytes for export_id=%s tenant=%s",
            export_id, tenant_id,
        )
        raise HTTPException(status_code=500, detail="Database error") from exc

    if record is None:
        raise HTTPException(
            status_code=404, detail=f"Export {export_id} not found."
        )

    return Response(
        content=record["epp_bytes"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{record["filename"]}"',
            "Content-Length": str(record["file_size"]),
            # Surface the digest so the frontend can verify integrity if it wants.
            "X-Content-SHA256": record["sha256"],
        },
    )
