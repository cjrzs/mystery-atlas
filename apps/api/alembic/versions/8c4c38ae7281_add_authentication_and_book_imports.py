"""add authentication and book imports

Revision ID: 8c4c38ae7281
Revises: 151d7467f12d
Create Date: 2026-07-22 12:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "8c4c38ae7281"
down_revision: Union[str, Sequence[str], None] = "151d7467f12d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=500), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_role"), "users", ["role"], unique=False)

    op.create_table(
        "book_imports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("original_name", sa.String(length=500), nullable=False),
        sa.Column("stored_path", sa.String(length=1000), nullable=False),
        sa.Column("source_format", sa.String(length=20), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=60), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("detected_title", sa.String(length=500), nullable=True),
        sa.Column("chapter_count", sa.Integer(), nullable=False),
        sa.Column("chapters", sa.JSON(), nullable=False),
        sa.Column("preview", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_path"),
    )
    op.create_index(
        op.f("ix_book_imports_content_hash"), "book_imports", ["content_hash"], unique=False
    )
    op.create_index(op.f("ix_book_imports_status"), "book_imports", ["status"], unique=False)
    op.create_index(op.f("ix_book_imports_user_id"), "book_imports", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_book_imports_user_id"), table_name="book_imports")
    op.drop_index(op.f("ix_book_imports_status"), table_name="book_imports")
    op.drop_index(op.f("ix_book_imports_content_hash"), table_name="book_imports")
    op.drop_table("book_imports")
    op.drop_index(op.f("ix_users_role"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
