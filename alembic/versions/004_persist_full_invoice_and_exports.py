"""Persist full invoice data + store generated EPP files for re-download.

Revision ID: 004
Revises: 003
Create Date: 2026-04-15

Three changes:

1. **Extend ``documents``** with every field the OCR extracts but the old
   schema dropped on the floor: sale/receipt/due dates, payment method,
   exchange rate, amount paid, contractor region, customer NIP,
   correction back-references, free-text notes, and a JSONB ``ocr_raw``
   column that captures the whole OCR payload as an audit trail / safety
   net for re-mapping when the schema evolves.

2. **Add ``document_vat_lines``** — one row per VAT rate. The old schema
   collapsed multi-rate invoices into the document totals, which made
   re-export inaccurate for invoices with mixed 23%/8%/zw rates.

3. **Add ``document_exports`` + ``export_documents``** — every generated
   ``.epp`` file is stored as BYTEA so the user can re-download it later
   without regenerating (which would risk drift if the tenant's
   accounting settings have changed in the meantime). Many-to-many join
   table supports batch exports that bundle multiple documents.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── documents: missing OCR fields ─────────────────────────────────────
    op.add_column("documents", sa.Column("issue_date", sa.Date))
    op.add_column("documents", sa.Column("sale_date", sa.Date))
    op.add_column("documents", sa.Column("receipt_date", sa.Date))
    op.add_column("documents", sa.Column("payment_due_date", sa.Date))
    op.add_column("documents", sa.Column("payment_method", sa.Text))
    op.add_column("documents", sa.Column("exchange_rate", sa.Numeric(18, 6)))
    op.add_column("documents", sa.Column("amount_paid", sa.Numeric(18, 4)))
    op.add_column("documents", sa.Column("contractor_region", sa.Text))
    op.add_column("documents", sa.Column("customer_nip", sa.Text))
    op.add_column("documents", sa.Column("transaction_id", sa.Text))
    op.add_column("documents", sa.Column("notes", sa.Text))
    op.add_column(
        "documents",
        sa.Column("is_correction", sa.Boolean, server_default=sa.text("false")),
    )
    op.add_column("documents", sa.Column("corrected_doc_number", sa.Text))
    op.add_column("documents", sa.Column("corrected_doc_date", sa.Date))
    # Audit / safety net: full OCR payload as JSONB so we can re-derive
    # any mapping in the future without re-running OCR.
    op.add_column("documents", sa.Column("ocr_raw", postgresql.JSONB))
    op.add_column(
        "documents",
        sa.Column(
            "updated_at",
            sa.DateTime,
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # Backfill issue_date from the legacy `date` column so existing rows
    # are not silently NULL on the new column. Done in raw SQL so the
    # migration is symmetric with downgrade().
    op.execute(
        "UPDATE documents SET issue_date = date WHERE issue_date IS NULL AND date IS NOT NULL"
    )

    op.create_index("idx_documents_issue_date", "documents", ["issue_date"])

    # ── document_vat_lines: per-rate breakdown ────────────────────────────
    op.create_table(
        "document_vat_lines",
        sa.Column("line_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "document_id",
            sa.Integer,
            sa.ForeignKey("documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("line_no", sa.Integer, nullable=False),
        sa.Column("vat_symbol", sa.Text, nullable=False),
        sa.Column("vat_rate", sa.Numeric(8, 4), nullable=False),
        sa.Column("net_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("vat_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("gross_amount", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.UniqueConstraint("document_id", "line_no", name="uq_vat_lines_document_line"),
    )
    op.create_index(
        "idx_vat_lines_document", "document_vat_lines", ["document_id"]
    )

    # ── document_exports: stored .epp files per tenant ────────────────────
    op.create_table(
        "document_exports",
        sa.Column("export_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Text, nullable=False),
        sa.Column("filename", sa.Text, nullable=False),
        sa.Column("epp_bytes", sa.LargeBinary, nullable=False),
        sa.Column("file_size", sa.Integer, nullable=False),
        sa.Column("sha256", sa.Text, nullable=False),
        sa.Column("epp_version", sa.Text),
        sa.Column("doc_count", sa.Integer, nullable=False, server_default="1"),
        # "single" for one-document exports, "batch" for /export endpoint runs
        sa.Column("export_kind", sa.Text, nullable=False, server_default="single"),
        sa.Column("created_at", sa.DateTime, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_exports_tenant", "document_exports", ["tenant_id"])
    op.create_index(
        "idx_exports_tenant_created",
        "document_exports",
        ["tenant_id", sa.text("created_at DESC")],
    )

    # Many-to-many join: an export contains one or more documents.
    op.create_table(
        "export_documents",
        sa.Column(
            "export_id",
            sa.Integer,
            sa.ForeignKey("document_exports.export_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "document_id",
            sa.Integer,
            sa.ForeignKey("documents.document_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index(
        "idx_export_documents_document",
        "export_documents",
        ["document_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_export_documents_document", table_name="export_documents")
    op.drop_table("export_documents")
    op.drop_index("idx_exports_tenant_created", table_name="document_exports")
    op.drop_index("idx_exports_tenant", table_name="document_exports")
    op.drop_table("document_exports")
    op.drop_index("idx_vat_lines_document", table_name="document_vat_lines")
    op.drop_table("document_vat_lines")
    op.drop_index("idx_documents_issue_date", table_name="documents")
    for col in (
        "updated_at", "ocr_raw", "corrected_doc_date", "corrected_doc_number",
        "is_correction", "notes", "transaction_id", "customer_nip",
        "contractor_region", "amount_paid", "exchange_rate", "payment_method",
        "payment_due_date", "receipt_date", "sale_date", "issue_date",
    ):
        op.drop_column("documents", col)
