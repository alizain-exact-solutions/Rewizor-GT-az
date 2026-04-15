"""Tenant identity table — thin helpers.

The ``tenants`` table is the single source of truth for tenant identity
across every sibling service that shares this Postgres instance. In the
host multi-tenant platform, tenant rows are normally provisioned by the
onboarding flow. This module provides a small ergonomic helper so the
accounting "save settings" endpoint can be the entry point for a new
tenant in single-service / standalone deployments too.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def ensure_tenant_exists(
    cursor, tenant_id: str, *, display_name: Optional[str] = None
) -> None:
    """Idempotently create the ``tenants`` row for *tenant_id*.

    Intended to be called at the start of the first write operation for a
    tenant (e.g. saving accounting settings), so the FK from
    ``accounting_settings``/``documents``/``document_exports`` into
    ``tenants`` never fails on first use.

    In the merged-host deployment the host platform is expected to
    create the row itself during onboarding; this helper is a no-op in
    that case thanks to ``ON CONFLICT DO NOTHING``.
    """
    cursor.execute(
        """
        INSERT INTO tenants (tenant_id, display_name)
        VALUES (%s, %s)
        ON CONFLICT (tenant_id) DO NOTHING
        """,
        (tenant_id, display_name),
    )
