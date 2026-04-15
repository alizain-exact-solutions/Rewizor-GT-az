"""Add supplier_region and supplier_country_code columns.

Revision ID: 002
Revises: 001
Create Date: 2026-04-06

**Now a no-op.** Migration ``001`` was later extended to include the
``supplier_region`` and ``supplier_country_code`` columns directly, so
re-adding them here would fail with ``DuplicateColumn`` on any fresh
database. The revision is kept so the chain 001 → 002 → 003 → 004 stays
continuous for databases that were stamped at 001 before the edit.
"""
from typing import Sequence, Union

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Intentionally empty — see module docstring.
    pass


def downgrade() -> None:
    # Intentionally empty — see module docstring.
    pass
