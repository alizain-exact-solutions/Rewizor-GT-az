"""Add supplier_region and supplier_country_code columns.

Revision ID: 002
Revises: 001
Create Date: 2026-04-06
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("supplier_region", sa.Text))
    op.add_column("documents", sa.Column("supplier_country_code", sa.Text))


def downgrade() -> None:
    op.drop_column("documents", "supplier_country_code")
    op.drop_column("documents", "supplier_region")
