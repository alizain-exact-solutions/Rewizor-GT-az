"""Rewizor GT OCR + EPP ingestion endpoint.

Upload a PDF/image, run OCR, return the generated ``.epp`` bytes. The
export is also persisted in the ``exports`` table so the caller can
re-download the exact bytes later through ``/api/v1/exports/{id}/download``.

Requires a row in ``business_details`` — managed through
``/api/v1/business-details``.
"""

import logging
import os
import uuid

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from src.core.settings import BusinessDetailsNotConfigured
from src.services.ocr_service import OCRExtractionError
from src.services.rewizor_service import cleanup_upload, process_and_export

logger = logging.getLogger(__name__)

MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB

router = APIRouter(tags=["rewizor"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp"}


def _validate_extension(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            ),
        )
    return ext


@router.post("/upload", summary="Upload a PDF invoice and receive the generated .epp")
async def upload_and_export(file: UploadFile = File(...)):
    """Run OCR on the uploaded document and return the .epp file.

    The ``X-Export-Id`` response header carries the DB id of the stored
    export so the caller can re-download the exact bytes later.
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
        if len(contents) > MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {MAX_UPLOAD_SIZE // (1024 * 1024)} MB limit",
            )
        with open(file_path, "wb") as f:
            f.write(contents)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to save uploaded file: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save uploaded file")

    try:
        result = process_and_export(file_path)
    except BusinessDetailsNotConfigured as e:
        cleanup_upload(file_path)
        raise HTTPException(
            status_code=412,
            detail=(
                "Business details not configured. POST to "
                "/api/v1/business-details before running an EPP export."
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
            "X-Export-Id": str(result["export_id"]),
        },
    )
