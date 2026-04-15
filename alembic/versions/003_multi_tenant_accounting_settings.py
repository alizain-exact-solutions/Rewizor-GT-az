"""Multi-tenant: create accounting_settings and add tenant_id to documents.

Revision ID: 003
Revises: 002
Create Date: 2026-04-15

Adds per-tenant accounting settings (the sender fields that were previously
env-var-driven) and scopes documents by tenant_id so invoices do not leak
between businesses when this service is embedded in a multi-tenant host
platform.

The host platform is responsible for providing the tenant identifier via
the ``X-Tenant-ID`` HTTP header; this migration only introduces the
storage and scoping, not an authentication layer.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── accounting_settings: one row per tenant ───────────────────────────
    op.create_table(
        "accounting_settings",
        sa.Column("tenant_id", sa.Text, primary_key=True),
        # Sender company (NAGLOWEK fields 7-11, 23)
        sa.Column("company_name", sa.Text, nullable=False),
        sa.Column("company_nip", sa.Text, nullable=False),
        sa.Column("company_country_code", sa.Text, server_default="PL", nullable=False),
        sa.Column("company_street", sa.Text),
        sa.Column("company_city", sa.Text),
        sa.Column("company_postal_code", sa.Text),
        # Subiekt GT branch identifiers (INFO fields 5-6)
        sa.Column("sender_id_code", sa.Text),
        sa.Column("sender_short_name", sa.Text),
        # Program/warehouse defaults (INFO fields 4, 12-14, 19)
        sa.Column("producing_program", sa.Text, server_default="Subiekt GT"),
        sa.Column("warehouse_code", sa.Text, server_default="MAG"),
        sa.Column("warehouse_name", sa.Text, server_default="Główny"),
        sa.Column("warehouse_description", sa.Text, server_default="Magazyn główny"),
        sa.Column("operator_name", sa.Text, server_default="Szef"),
        # Mapper defaults
        sa.Column(
            "default_payment_term_days",
            sa.Integer,
            server_default="14",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime, server_default=sa.text("NOW()")),
    )

    # ── documents: scope by tenant ────────────────────────────────────────
    # Existing rows keep a sentinel tenant_id so back-compat is preserved
    # until the host platform has fully transitioned.
    op.add_column(
        "documents",
        sa.Column(
            "tenant_id",
            sa.Text,
            nullable=False,
            server_default="default",
        ),
    )
    op.create_index("idx_documents_tenant", "documents", ["tenant_id"])
    op.create_index(
        "idx_documents_tenant_status",
        "documents",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("idx_documents_tenant_status", table_name="documents")
    op.drop_index("idx_documents_tenant", table_name="documents")
    op.drop_column("documents", "tenant_id")
    op.drop_table("accounting_settings")
