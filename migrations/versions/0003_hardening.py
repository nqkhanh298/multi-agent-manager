"""Persist run budgets, worker heartbeat and model usage counters.

Revision ID: 0003_hardening
Revises: 0002_tool_journal
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_hardening"
down_revision = "0002_tool_journal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("budget_usd", sa.Float(), nullable=False, server_default="5"))
    op.add_column("runs", sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0"))
    op.add_column(
        "runs", sa.Column("max_seconds", sa.Integer(), nullable=False, server_default="1800")
    )
    op.add_column("runs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "agent_executions",
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_executions",
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "agent_executions", sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("agent_executions", "cost_usd")
    op.drop_column("agent_executions", "output_tokens")
    op.drop_column("agent_executions", "input_tokens")
    op.drop_column("runs", "heartbeat_at")
    op.drop_column("runs", "max_seconds")
    op.drop_column("runs", "spent_usd")
    op.drop_column("runs", "budget_usd")
