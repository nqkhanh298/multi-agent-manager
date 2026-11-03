"""Durable execution and tool-call intent journal.

Revision ID: 0002_tool_journal
Revises: 0001_platform
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_tool_journal"
down_revision = "0001_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("tasks.id"), nullable=False, unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "tool_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "execution_id", sa.String(36), sa.ForeignKey("agent_executions.id"), nullable=False
        ),
        sa.Column("idempotency_key", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("arguments", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("output_ref", sa.Text(), nullable=True),
    )
    op.create_index("ix_tool_calls_execution_id", "tool_calls", ["execution_id"])


def downgrade() -> None:
    op.drop_table("tool_calls")
    op.drop_table("agent_executions")
