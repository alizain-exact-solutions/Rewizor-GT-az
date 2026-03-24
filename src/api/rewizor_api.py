"""Rewizor GT EPP export endpoints."""

import logging
import os
import uuid
from typing import List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from src.epp.constants import DOC_TYPE_PURCHASE_INVOICE, VALID_DOC_TYPES
from src.services.rewizor_service import export_from_db, process_and_export

logger = logging.getLogger(__name__)

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
async def rewizor_upload_and_export(
    file: UploadFile = File(...),
):
    """Upload a document, run Rewizor OCR, and return the .epp file.

    The document type (FZ, FS, KZ, KS, FZK, FSK, KZK, KSK, WB, RK, PK, DE)
    is auto-detected by OCR from the document content.

    The response is the generated EPP file (Windows-1250 encoded)
    ready for import into Rewizor GT.
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
        result = process_and_export(file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found after upload")
    except Exception as e:
        logger.error("Rewizor export failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Rewizor export failed: {e}")

    return Response(
        content=result["epp_bytes"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{result["epp_filename"]}"',
        },
    )


# ── Async OCR + Export via Celery ────────────────────────────────────────────

@router.post("/upload/async")
async def rewizor_upload_async(
    file: UploadFile = File(...),
):
    """Upload document and queue Rewizor OCR + export as a Celery task.

    The document type is auto-detected by OCR.
    Returns a ``task_id`` to poll for the result.
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

    from src.workers.tasks.rewizor_export_task import rewizor_export_task

    task = rewizor_export_task.delay(file_path)
    return {"message": "Queued for Rewizor export", "file": unique_name, "task_id": task.id}


# ── DB Batch Export ──────────────────────────────────────────────────────────

@router.post("/export")
async def rewizor_db_export(
    document_ids: Optional[List[int]] = Query(None, description="Specific document IDs"),
    status: str = Query("PENDING", description="Document status filter"),
    doc_type: str = Query(DOC_TYPE_PURCHASE_INVOICE, description="Document type"),
):
    """Generate an EPP file from documents already stored in the database.

    Either provide explicit ``document_ids`` or filter by ``status``.
    """
    if doc_type not in VALID_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid doc_type '{doc_type}'")

    try:
        result = export_from_db(
            document_ids=document_ids,
            status=status,
            doc_type=doc_type,
        )
    except Exception as e:
        logger.error("Rewizor DB export failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Export failed: {e}")

    if result["count"] == 0:
        raise HTTPException(status_code=404, detail="No documents found for export")

    return Response(
        content=result["epp_bytes"],
        media_type="application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{result["epp_filename"]}"',
        },
    )
