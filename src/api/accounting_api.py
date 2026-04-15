"""Accounting settings endpoints — per-tenant sender configuration.

The frontend "Accounting details" page reads and writes these values. At
EPP export time the service loads the current tenant's row and populates
every sender field of the [INFO] section from it.

Authentication (tenant identification) is header-based — see
:func:`src.api.tenant.get_tenant_id` for details.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.api.schemas import (
    AccountingSettingsCreate,
    AccountingSettingsResponse,
)
from src.api.tenant import get_tenant_id
from src.core.db import db_session
from src.repositories.accounting_repo import (
    delete_settings,
    get_settings,
    upsert_settings,
)
from src.repositories.tenant_repo import ensure_tenant_exists

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/accounting", tags=["accounting"])


@router.get(
    "/settings",
    response_model=AccountingSettingsResponse,
    summary="Get accounting settings for the current tenant",
    responses={
        404: {"description": "No settings configured for this tenant yet."},
    },
)
@limiter.limit("60/minute")
async def read_settings(
    request: Request,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Return the current tenant's accounting settings.

    Returns **404** if the tenant has not yet saved their details — the
    frontend should interpret that as "render an empty form" rather than
    as an error.
    """
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            row = get_settings(cursor, tenant_id)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to read accounting settings for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No accounting settings configured for tenant '{tenant_id}'.",
        )
    return AccountingSettingsResponse(**row)


@router.put(
    "/settings",
    response_model=AccountingSettingsResponse,
    status_code=status.HTTP_200_OK,
    summary="Create or replace accounting settings for the current tenant",
)
@limiter.limit("30/minute")
async def upsert_settings_endpoint(
    request: Request,
    payload: AccountingSettingsCreate,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Save the accounting details form.

    A PUT is idempotent — calling it twice with the same body produces the
    same stored state. The row is keyed by the header-supplied tenant id,
    so two different tenants can POST identical bodies without collision.
    """
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            # In the merged-host deployment the host manages tenants; here
            # we ensure the FK target exists so single-service / standalone
            # usage doesn't require a separate onboarding call.
            ensure_tenant_exists(
                cursor, tenant_id, display_name=payload.company_name
            )
            row = upsert_settings(cursor, tenant_id, payload.model_dump())
            cursor.close()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to upsert accounting settings for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    logger.info("Accounting settings saved for tenant %s", tenant_id)
    return AccountingSettingsResponse(**row)


@router.delete(
    "/settings",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove accounting settings for the current tenant",
)
@limiter.limit("10/minute")
async def delete_settings_endpoint(
    request: Request,
    tenant_id: Annotated[str, Depends(get_tenant_id)],
):
    """Remove the tenant's configuration (e.g. on tenant offboarding)."""
    try:
        with db_session() as conn:
            cursor = conn.cursor()
            removed = delete_settings(cursor, tenant_id)
            cursor.close()
    except Exception as exc:
        logger.exception("Failed to delete accounting settings for tenant %s", tenant_id)
        raise HTTPException(status_code=500, detail="Database error") from exc

    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No accounting settings configured for tenant '{tenant_id}'.",
        )
    return None
