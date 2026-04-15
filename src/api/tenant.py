"""FastAPI dependency for extracting the current tenant id.

This service is designed to be embedded into a larger multi-tenant host
platform. The host is responsible for authentication and for supplying
the tenant identifier on every request via the **``X-Tenant-ID``** HTTP
header.

During local development or when the caller is a trusted backend service,
the header may be absent; in that case the dependency falls back to the
``DEFAULT_TENANT_ID`` environment variable (defaults to ``"default"``).
Set ``REQUIRE_TENANT_HEADER=1`` in production so a missing header returns
``400`` instead of silently falling back.
"""

import logging
import os
import re
from typing import Annotated

from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)

# Accept common identifier shapes: alphanumeric, underscore, dash, dot, up to
# 50 chars. Upper bound matches the ``VARCHAR(50)`` column in the ``tenants``
# table so an id that passes this regex is guaranteed to fit in the database.
_TENANT_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,50}$")


def _is_valid(tenant_id: str) -> bool:
    return bool(_TENANT_ID_RE.match(tenant_id))


async def get_tenant_id(
    x_tenant_id: Annotated[
        str | None,
        Header(
            alias="X-Tenant-ID",
            description=(
                "Identifier of the current tenant. Provided by the host "
                "multi-tenant platform on every request."
            ),
        ),
    ] = None,
) -> str:
    """Resolve the tenant id for the current request.

    Precedence:
      1. ``X-Tenant-ID`` HTTP header.
      2. ``DEFAULT_TENANT_ID`` environment variable (dev/test only).
      3. Literal ``"default"``.

    When ``REQUIRE_TENANT_HEADER=1`` the environment fallback is disabled
    and a missing or invalid header returns HTTP 400.
    """
    require_header = os.getenv("REQUIRE_TENANT_HEADER", "0").lower() in {
        "1",
        "true",
        "yes",
    }

    if x_tenant_id:
        tenant_id = x_tenant_id.strip()
        if not _is_valid(tenant_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Invalid X-Tenant-ID header. Must be 1-50 characters of "
                    "[A-Za-z0-9_.-]."
                ),
            )
        return tenant_id

    if require_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Tenant-ID header is required.",
        )

    fallback = os.getenv("DEFAULT_TENANT_ID", "default").strip() or "default"
    logger.debug("No X-Tenant-ID header; falling back to %r", fallback)
    return fallback
