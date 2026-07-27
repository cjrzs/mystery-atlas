"""add reader preferences

Revision ID: 9d5e3b7a2c10
Revises: 62b9c2e7d1a4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d5e3b7a2c10"
down_revision: str | Sequence[str] | None = "62b9c2e7d1a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "reader_preferences",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "reader_preferences")
