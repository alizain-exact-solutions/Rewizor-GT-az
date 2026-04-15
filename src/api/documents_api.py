"""Document read and regenerate endpoints (tenant-scoped).

Once an invoice has been uploaded through ``POST /rewizor/upload`` it is
persisted to the database. The frontend uses the endpoints here to:

* browse stored documents (``GET /documents``),
* open one (``GET /documents/{id}``) with the full per-rate VAT breakdown,
* regenerate a fresh ``.epp`` against the tenant's *current* accounting
  settings (``POST /documents/{id}/regenerate``) — the original export is
  preserved too, so the user can always re-download the original bytes
  via ``/exports``.

Every query is routed through the repository layer, which filters on
``tenant_id`` — two tenants sharing one database instance cannot read
each other's invoices.
"""

import logging
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.schemas import (
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
)
from src.api.tenant import get_tenant_id
from src.core.db import db_session
from src.epp.constants import VALID_DOC_TYPES
from src.repositories.document_repo import (
    count_documents,
    get_document,
    list_documents,
)
from src.services.rewizor_service import (
    AccountingNotConfigured,
    regenerate_export,
)

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/documents", tags=["documents"])


# ── List ──────────────────────────────────────────────────────────────────

@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List stored documents for the current tenant",
)
@limiter.limit("60/minute")
async def list_documents_endpoint(
    request: Request,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    status_filter: Optional[str] = Query(
        None,
        alias="status",
        description="Filter by status: PENDING | EXPORTED",
    ),
    doc_type: Optional[str] = Query(
        None,
        description="Filter by Rewizor document type (FZ/FS/KZ/…).",
    ),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Paginated listing of stored documents (VAT breakdown omitted — cheap).

    Use :func:`read_document` for the full per-rate breakdown.
    """
    if doc_type is not None and doc_type not in VALID_DOC_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Invalid doc_type '{doc_type}'"
        )

    try:
        with db_session() as conn:
            cursor = conn.cursor()
            rows = list_documents(
                cursor,
                tenant_id=tenant_id,
                status=status_filter,
                doc_type=doc_type,
                limit=limit,
                offset=offset,
            )
            total = count_documents(
                cursor,
                tenant_id=tenant_id,
                status=status_filter,
                doc_type=doc_type,
            )
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to list documents for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    return DocumentListResponse(
        items=[DocumentSummary(**row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


# ── Detail ────────────────────────────────────────────────────────────────

@router.get(
    "/{document_id}",
    response_model=DocumentDetail,
    summary="Get full detail for one document (including VAT breakdown)",
    responses={404: {"description": "Document not found for this tenant."}},
)
@limiter.limit("120/minute")
async def read_document(
    request: Request,
    document_id: int,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Return a single document with its per-rate VAT breakdown.

    Scoped to the caller's tenant — looking up another tenant's document
    id returns **404**, never 403 (so we don't leak existence).
    """
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            document = get_document(cursor, document_id, tenant_id=tenant_id)
            cursor.close()
    except Exception as exc:
        logger.exception(
            "Failed to load document %s for tenant %s", document_id, tenant_id
        )
        raise HTTPException(status_code=500, detail="Database error") from exc

    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        )
    return DocumentDetail(**document)


# ── Regenerate EPP on demand ──────────────────────────────────────────────

@router.post(
    "/{document_id}/regenerate",
    summary="Regenerate a .epp from a stored document and return the bytes",
    responses={
        404: {"description": "Document not found for this tenant."},
        412: {"description": "Tenant has no accounting_settings row."},
    },
)
@limiter.limit("30/minute")
async def regenerate_document_export(
    request: Request,
    document_id: int,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Re-map a stored document and generate a **fresh** ``.epp`` file.

    The new export uses the tenant's *current* accounting settings, so
    this is the right endpoint to use if the settings (address, NIP,
    operator name, payment terms…) changed since the original export.

    The fresh export is also persisted (``export_kind='regenerated'``),
    so it stays re-downloadable through ``/exports/{export_id}/download``.
    """
    try:
        result = regenerate_export(tenant_id=tenant_id, document_id=document_id)
    except AccountingNotConfigured as exc:
        raise HTTPException(
            status_code=412,
            detail=(
                "Accounting details not configured for this tenant. "
                "Save the Accounting Details form before regenerating."
            ),
        ) from exc
    except LookupError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found.",
        ) from exc
    except Exception as exc:
        logger.exception(
            "Regenerate failed for tenant=%s document_id=%s", tenant_id, document_id
        )
        raise HTTPException(status_code=500, detail="Regeneration failed") from exc

    return Response(
        content=result["epp_bytes"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{result["epp_filename"]}"',
            # Surface the newly-persisted export id so the frontend can link
            # the download into its exports history immediately.
            "X-Export-Id": str(result["export_id"]),
        },
    )
