"""Stored EPP export endpoints — list, metadata, and re-download.

Every generated ``.epp`` file is persisted in the ``exports`` table so
the user can re-download the exact bytes at any point.
"""

import logging

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from src.api.schemas import ExportListResponse, ExportSummary
from src.core.db import db_session
from src.repositories.exports_repo import (
    count_exports,
    get_export_bytes,
    get_export_metadata,
    list_exports,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])


@router.get(
    "",
    response_model=ExportListResponse,
    summary="List stored EPP exports",
)
async def list_exports_endpoint(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated listing of stored exports — metadata only, no bytes."""
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            rows = list_exports(cursor, limit=limit, offset=offset)
            total = count_exports(cursor)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to list exports")
        raise HTTPException(status_code=500, detail="Database error") from exc

    return ExportListResponse(
        items=[ExportSummary(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{export_id}",
    response_model=ExportSummary,
    summary="Get metadata for a stored EPP export",
    responses={404: {"description": "Export not found."}},
)
async def read_export(export_id: int):
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            metadata = get_export_metadata(cursor, export_id)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to load export %s", export_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    if metadata is None:
        raise HTTPException(status_code=404, detail=f"Export {export_id} not found.")
    return ExportSummary(**metadata)


@router.get(
    "/{export_id}/download",
    summary="Download the stored .epp bytes",
    response_class=Response,
    responses={404: {"description": "Export not found."}},
)
async def download_export(export_id: int):
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            record = get_export_bytes(cursor, export_id)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to fetch export bytes for export_id=%s", export_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    if record is None:
        raise HTTPException(status_code=404, detail=f"Export {export_id} not found.")

    return Response(
        content=record["epp_bytes"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{record["filename"]}"',
            "Content-Length": str(record["file_size"]),
            "X-Content-SHA256": record["sha256"],
        },
    )
