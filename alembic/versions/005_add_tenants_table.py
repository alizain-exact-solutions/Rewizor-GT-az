"""Introduce the central ``tenants`` table and FK constraints.

Revision ID: 005
Revises: 004
Create Date: 2026-04-15

Aligns this service with the shared-schema row-level tenant isolation
pattern used across sibling services in the host platform:

* a single ``tenants`` table is the source of truth for tenant identity,
* every tenant-owned table (``documents``, ``accounting_settings``,
  ``document_exports``) has its ``tenant_id`` typed as ``VARCHAR(50)``
  and FK-referenced into ``tenants(tenant_id)``,
* the FK makes unknown/typo'd tenant ids fail at insert time instead of
  silently creating orphaned rows that leak between businesses.

The migration also seeds a ``'default'`` tenant row so single-tenant
development usage keeps working out of the box. Any tenant ids already
present on existing rows (e.g. after a previous deployment) are
back-filled into ``tenants`` so the FK can be added without manual
cleanup.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── tenants: single source of truth for tenant identity ───────────────
    op.create_table(
        "tenants",
        sa.Column("tenant_id", sa.String(50), primary_key=True),
        sa.Column("display_name", sa.Text),
        sa.Column(
            "created_at", sa.DateTime, server_default=sa.text("NOW()"), nullable=False
        ),
    )

    # Back-fill: pull every distinct tenant_id already used by tenant-owned
    # tables, plus the conventional 'default' used by dev single-tenant
    # mode. ``ON CONFLICT DO NOTHING`` keeps the seed idempotent if someone
    # re-runs the migration after a partial rollback.
    op.execute(
        """
        INSERT INTO tenants (tenant_id, display_name)
        SELECT tenant_id, NULL FROM (
            SELECT DISTINCT tenant_id FROM documents
            UNION
            SELECT DISTINCT tenant_id FROM accounting_settings
            UNION
            SELECT DISTINCT tenant_id FROM document_exports
            UNION ALL
            SELECT 'default'
        ) t
        ON CONFLICT (tenant_id) DO NOTHING
        """
    )

    # ── Align column types with the cross-service pattern ────────────────
    # TEXT and VARCHAR(50) are functionally equivalent in Postgres, but
    # matching the sibling-service convention keeps the merged schema tidy.
    for table in ("documents", "accounting_settings", "document_exports"):
        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.Text(),
            type_=sa.String(50),
            existing_nullable=False,
        )

    # ── FK: every tenant-scoped table points at the central table ────────
    op.create_foreign_key(
        "fk_documents_tenant",
        "documents",
        "tenants",
        ["tenant_id"],
        ["tenant_id"],
    )
    op.create_foreign_key(
        "fk_accounting_settings_tenant",
        "accounting_settings",
        "tenants",
        ["tenant_id"],
        ["tenant_id"],
    )
    op.create_foreign_key(
        "fk_document_exports_tenant",
        "document_exports",
        "tenants",
        ["tenant_id"],
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_document_exports_tenant", "document_exports", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_accounting_settings_tenant", "accounting_settings", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_documents_tenant", "documents", type_="foreignkey"
    )

    for table in ("documents", "accounting_settings", "document_exports"):
        op.alter_column(
            table,
            "tenant_id",
            existing_type=sa.String(50),
            type_=sa.Text(),
            existing_nullable=False,
        )

    op.drop_table("tenants")
