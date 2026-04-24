"""CRUD for the ``business_details`` singleton row.

The table is constrained to at most one row (``CHECK (id = 1)``) so every
query operates on ``WHERE id = 1`` without pagination concerns.
"""

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


_COLUMNS = (
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

_SELECT = """
    id, company_name, company_nip, company_country_code,
    company_street, company_city, company_postal_code,
    sender_id_code, sender_short_name,
    producing_program, warehouse_code, warehouse_name,
    warehouse_description, operator_name,
    default_payment_term_days, created_at, updated_at
"""


def get_details(cursor) -> Optional[Dict[str, Any]]:
    """Return the business details row, or ``None`` if unconfigured."""
    cursor.execute(f"SELECT {_SELECT} FROM business_details WHERE id = 1")
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def upsert_details(cursor, values: Dict[str, Any]) -> Dict[str, Any]:
    """Create or replace the singleton business_details row."""
    payload = {k: values.get(k) for k in _COLUMNS if k in values}

    for required in ("company_name", "company_nip"):
        if not payload.get(required):
            raise ValueError(f"{required} must not be empty")

    insert_cols = ["id", *payload.keys()]
    insert_vals = [1, *payload.values()]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(insert_cols)
    updates = ", ".join(f"{col} = EXCLUDED.{col}" for col in payload.keys())

    cursor.execute(
        f"""
        INSERT INTO business_details ({col_list})
        VALUES ({placeholders})
        ON CONFLICT (id) DO UPDATE SET {updates}, updated_at = NOW()
        RETURNING {_SELECT}
        """,
        insert_vals,
    )
    row = cursor.fetchone()
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row))


def delete_details(cursor) -> bool:
    """Remove the singleton row. Returns True if a row was removed."""
    cursor.execute("DELETE FROM business_details WHERE id = 1")
    return cursor.rowcount > 0
