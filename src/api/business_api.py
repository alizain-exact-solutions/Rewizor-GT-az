"""Business details endpoints — sender/accounting configuration.

One row per deployment. The EPP upload endpoint reads this row to
populate the [INFO] section of every generated .epp file.

* ``POST   /business-details``  — create or replace (idempotent).
* ``GET    /business-details``  — read current row (404 if unset).
* ``DELETE /business-details``  — clear the row.
"""

import logging

from fastapi import APIRouter, HTTPException, status

from src.api.schemas import BusinessDetailsCreate, BusinessDetailsResponse
from src.core.db import db_session
from src.repositories.business_repo import (
    delete_details,
    get_details,
    upsert_details,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/business-details", tags=["business-details"])


@router.get(
    "",
    response_model=BusinessDetailsResponse,
    summary="Get the current business details",
    responses={404: {"description": "No business details configured yet."}},
)
async def read_details():
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            row = get_details(cursor)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to read business details")
        raise HTTPException(status_code=500, detail="Database error") from exc

    if row is None:
        raise HTTPException(
            status_code=404, detail="No business details configured yet."
        )
    return BusinessDetailsResponse(**row)


@router.post(
    "",
    response_model=BusinessDetailsResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or replace the business details",
)
async def create_or_update_details(payload: BusinessDetailsCreate):
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            row = upsert_details(cursor, payload.model_dump())
            cursor.close()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to upsert business details")
        raise HTTPException(status_code=500, detail="Database error") from exc

    logger.info("Business details saved (company=%s)", row.get("company_name"))
    return BusinessDetailsResponse(**row)


@router.delete(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove the current business details",
    responses={404: {"description": "Nothing to delete."}},
)
async def delete_details_endpoint():
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            removed = delete_details(cursor)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to delete business details")
        raise HTTPException(status_code=500, detail="Database error") from exc

    if not removed:
        raise HTTPException(
            status_code=404, detail="No business details configured."
        )
    return None
