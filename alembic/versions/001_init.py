"""Initial schema — single exports table.

Revision ID: 001_init
Revises:
Create Date: 2026-04-24

Single-tenant deployment. One table holds each generated EPP file plus
the invoice metadata and raw OCR payload needed for listing, search,
and audit.
"""

from alembic import op


revision = "001_init"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS exports (
            id              SERIAL       PRIMARY KEY,
            filename        TEXT         NOT NULL,
            epp_bytes       BYTEA        NOT NULL,
            file_size       INTEGER      NOT NULL,
            sha256          CHAR(64)     NOT NULL,
            epp_version     TEXT,
            invoice_number  TEXT,
            doc_type        TEXT,
            issue_date      DATE,
            currency        CHAR(3),
            net_amount      NUMERIC(14, 2),
            vat_amount      NUMERIC(14, 2),
            gross_amount    NUMERIC(14, 2),
            contractor_name TEXT,
            contractor_nip  TEXT,
            ocr_raw         JSONB,
            created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS exports_created_at_idx
            ON exports (created_at DESC);

        CREATE INDEX IF NOT EXISTS exports_invoice_number_idx
            ON exports (invoice_number);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS exports CASCADE;")
