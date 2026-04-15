"""Per-tenant accounting_settings CRUD.

Each tenant has at most one row. The service layer loads this row to build
the EPP [INFO] section at export time; the API layer lets the frontend
manage it through the "Accounting details" page.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# All columns that exist on the accounting_settings table — used by the
# upsert so we don't have to maintain two parallel field lists.
_ALL_COLUMNS = (
    "company_name",
    "company_nip",
    "company_country_code",
    "company_street",
    "company_city",
    "company_postal_code",
    "sender_id_code",
    "sender_short_name",
    "producing_program",
    "warehouse_code",
    "warehouse_name",
    "warehouse_description",
    "operator_name",
    "default_payment_term_days",
)


def get_settings(cursor, tenant_id: str) -> Optional[Dict[str, Any]]:
    """Return the accounting settings row for *tenant_id* or ``None``."""
    cursor.execute(
        """
        SELECT tenant_id, company_name, company_nip, company_country_code,
               company_street, company_city, company_postal_code,
               sender_id_code, sender_short_name,
               producing_program, warehouse_code, warehouse_name,
               warehouse_description, operator_name,
               default_payment_term_days,
               created_at, updated_at
        FROM accounting_settings
        WHERE tenant_id = %s
        """,
        (tenant_id,),
    )
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def upsert_settings(
    cursor,
    tenant_id: str,
    values: Dict[str, Any],
) -> Dict[str, Any]:
    """Create or replace the accounting settings row for *tenant_id*.

    Unknown keys in *values* are ignored; missing optional keys keep their
    previous DB values (for UPDATE) or the column default (for INSERT).
    Returns the post-write row.
    """
    # Only keep keys we know about to avoid SQL injection via column names.
    payload = {k: values.get(k) for k in _ALL_COLUMNS if k in values}
    if not payload:
        # No-op upsert still needs to hit the INSERT path if the tenant is new
        payload = {}

    # Guarantee NOT NULL columns if the row doesn't exist yet.
    for required in ("company_name", "company_nip"):
        if required in payload and payload[required] in (None, ""):
            raise ValueError(f"{required} must not be empty")

    insert_cols = ["tenant_id", *payload.keys()]
    insert_vals = [tenant_id, *payload.values()]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)

    # For the UPDATE branch, skip tenant_id — we never overwrite the key.
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in payload.keys())
    update_clause = (
        f"DO UPDATE SET {updates}, updated_at = NOW()"
        if payload
        else "DO NOTHING"
    )

    cursor.execute(
        f"""
        INSERT INTO accounting_settings ({col_list})
        VALUES ({placeholders})
        ON CONFLICT (tenant_id) {update_clause}
        RETURNING tenant_id, company_name, company_nip, company_country_code,
                  company_street, company_city, company_postal_code,
                  sender_id_code, sender_short_name,
                  producing_program, warehouse_code, warehouse_name,
                  warehouse_description, operator_name,
                  default_payment_term_days, created_at, updated_at
        """,
        insert_vals,
    )
    row = cursor.fetchone()
    if row is None:
        # DO NOTHING path — re-read the existing row so callers get consistent data.
        return get_settings(cursor, tenant_id) or {}
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def delete_settings(cursor, tenant_id: str) -> bool:
    """Remove a tenant's settings. Returns True when a row was removed."""
    cursor.execute(
        "DELETE FROM accounting_settings WHERE tenant_id = %s",
        (tenant_id,),
    )
    return cursor.rowcount > 0
