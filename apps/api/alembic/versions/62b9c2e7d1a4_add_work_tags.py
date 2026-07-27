"""add book tags

Revision ID: 62b9c2e7d1a4
Revises: 3f7c2a91d4e8
Create Date: 2026-07-23 22:30:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "62b9c2e7d1a4"
down_revision: Union[str, Sequence[str], None] = "3f7c2a91d4e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "works",
        sa.Column("tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )
    op.add_column(
        "book_imports",
        sa.Column("detected_tags", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("book_imports", "detected_tags")
    op.drop_column("works", "tags")
