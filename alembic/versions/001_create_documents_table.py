"""Create documents table.

Revision ID: 001
Revises: None
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("document_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("invoice_number", sa.Text),
        sa.Column("total_amount", sa.Numeric),
        sa.Column("currency", sa.Text, server_default="PLN"),
        sa.Column("vat_amount", sa.Numeric),
        sa.Column("gross_amount", sa.Numeric),
        sa.Column("net_amount", sa.Numeric),
        sa.Column("date", sa.Date),
        sa.Column("vendor", sa.Text),
        sa.Column("customer", sa.Text),
        sa.Column("contractor_nip", sa.Text),
        sa.Column("contractor_name", sa.Text),
        sa.Column("contractor_street", sa.Text),
        sa.Column("contractor_city", sa.Text),
        sa.Column("contractor_postal_code", sa.Text),
        sa.Column("contractor_country", sa.Text, server_default="PL"),
        sa.Column("supplier_region", sa.Text),
        sa.Column("supplier_country_code", sa.Text),
        sa.Column("doc_type", sa.Text, server_default="FZ"),
        sa.Column("status", sa.Text, server_default="PENDING"),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_documents_status", "documents", ["status"])
    op.create_index("idx_documents_doc_type", "documents", ["doc_type"])


def downgrade() -> None:
    op.drop_index("idx_documents_doc_type")
    op.drop_index("idx_documents_status")
    op.drop_table("documents")
