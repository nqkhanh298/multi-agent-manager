"""Select the real Codex agent engine for new runs.

Revision ID: 0004_codex_engine
Revises: 0003_hardening
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_codex_engine"
down_revision = "0003_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("engine", sa.String(20), nullable=False, server_default="demo"))


def downgrade() -> None:
    op.drop_column("runs", "engine")
