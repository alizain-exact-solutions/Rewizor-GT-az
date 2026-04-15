"""Rewizor GT OCR + EPP ingestion endpoint.

The ``/rewizor`` prefix is reserved for the **OCR-driven** ingestion
path — upload a PDF/image, run Rewizor OCR on it, and return the
generated ``.epp`` bytes. Pure read/regenerate actions on already-
persisted documents live under ``/documents`` (see
:mod:`src.api.documents_api`).

The endpoint is **tenant-scoped** — the caller supplies the tenant id
via the ``X-Tenant-ID`` header (see :func:`src.api.tenant.get_tenant_id`).
The service looks up that tenant's saved accounting settings (configured
on the frontend through ``/api/v1/accounting/settings``) and uses them to
populate the EPP [INFO] section.
"""

import logging
import os
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.tenant import get_tenant_id
from src.services.ocr_service import OCRExtractionError
from src.services.rewizor_service import (
    AccountingNotConfigured,
    cleanup_upload,
    process_and_export,
)

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(tags=["rewizor"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


def _validate_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return ext


# ── OCR + Export ─────────────────────────────────────────────────────────────

@router.post("/upload")
@limiter.limit("10/minute")
async def rewizor_upload_and_export(
    request: Request,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
    file: UploadFile = File(...),
):
    """Upload a document, run Rewizor OCR, and return the .epp file.

    The document type (FZ, FS, KZ, KS, FZK, FSK, KZK, KSK, WB, RK, PK, DE)
    is auto-detected by the OCR from the document content.

    **Requires** the tenant's Accounting Details to be saved first via
    ``PUT /api/v1/accounting/settings`` — otherwise returns **412
    Precondition Failed** so the frontend can redirect the operator to
    that page.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    ext = _validate_extension(file.filename)
    unique_name = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, unique_name)

    try:
        contents = await file.read()
        if not contents:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
        with open(file_path, "wb") as f:
            f.write(contents)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to save uploaded file: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    try:
        result = process_and_export(file_path, tenant_id=tenant_id)
    except AccountingNotConfigured as e:
        cleanup_upload(file_path)
        raise HTTPException(
            status_code=412,
            detail=(
                "Accounting details not configured for this tenant. "
                "Save the Accounting Details form before running an EPP export."
            ),
        ) from e
    except FileNotFoundError:
        cleanup_upload(file_path)
        raise HTTPException(status_code=404, detail="File not found after upload")
    except OCRExtractionError as e:
        logger.error("OCR extraction failed: %s", e)
        cleanup_upload(file_path)
        raise HTTPException(status_code=422, detail=f"OCR extraction failed: {e}")
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        cleanup_upload(file_path)
        raise HTTPException(status_code=500, detail="Server configuration error")
    except Exception as e:
        logger.error("Rewizor export failed: %s", e)
        cleanup_upload(file_path)
        raise HTTPException(status_code=500, detail=f"Rewizor export failed: {e}")

    cleanup_upload(file_path)

    return Response(
        content=result["epp_bytes"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{result["epp_filename"]}"',
        },
    )


# NOTE: bulk export from already-persisted documents was removed — the
# single-doc case is covered by ``POST /documents/{id}/regenerate`` and
# re-downloading original bytes is covered by ``GET /exports/{id}/download``.
