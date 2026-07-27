"""add analysis heartbeat metadata

Revision ID: b7a1c4d9e2f0
Revises: 9d5e3b7a2c10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7a1c4d9e2f0"
down_revision: str | Sequence[str] | None = "9d5e3b7a2c10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analysis_jobs",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("current_call_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("stage_detail", sa.String(length=300), nullable=True),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column(
            "response_chars",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "analysis_jobs",
        sa.Column(
            "content_idle_seconds",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("analysis_jobs", "content_idle_seconds")
    op.drop_column("analysis_jobs", "response_chars")
    op.drop_column("analysis_jobs", "stage_detail")
    op.drop_column("analysis_jobs", "current_call_id")
    op.drop_column("analysis_jobs", "heartbeat_at")
