"""Add business_details singleton table.

Revision ID: 002_business_details
Revises: 001_init
Create Date: 2026-04-24

One row per deployment — identified by a ``CHECK (id = 1)`` constraint —
holds the sender / accounting details written into the EPP [INFO] section
of every generated .epp file. Managed through ``/api/v1/business-details``.
"""

from alembic import op


revision = "002_business_details"
down_revision = "001_init"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS business_details (
            id                         INTEGER     PRIMARY KEY DEFAULT 1 CHECK (id = 1),
            company_name               TEXT        NOT NULL,
            company_nip                TEXT        NOT NULL,
            company_country_code       CHAR(2)     NOT NULL DEFAULT 'PL',
            company_street             TEXT,
            company_city               TEXT,
            company_postal_code        TEXT,
            sender_id_code             TEXT,
            sender_short_name          TEXT,
            producing_program          TEXT        NOT NULL DEFAULT 'Subiekt GT',
            warehouse_code             TEXT        NOT NULL DEFAULT 'MAG',
            warehouse_name             TEXT        NOT NULL DEFAULT 'Główny',
            warehouse_description      TEXT        NOT NULL DEFAULT 'Magazyn główny',
            operator_name              TEXT        NOT NULL DEFAULT 'Szef',
            default_payment_term_days  INTEGER     NOT NULL DEFAULT 14,
            created_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at                 TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS business_details CASCADE;")
