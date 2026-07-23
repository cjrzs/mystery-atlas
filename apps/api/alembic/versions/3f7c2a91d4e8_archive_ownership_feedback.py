"""archive ownership feedback and reading records

Revision ID: 3f7c2a91d4e8
Revises: 8c4c38ae7281
Create Date: 2026-07-23 01:00:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "3f7c2a91d4e8"
down_revision: Union[str, Sequence[str], None] = "8c4c38ae7281"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("users", sa.Column("can_publish", sa.Boolean(), server_default=sa.true(), nullable=False))
    op.add_column("users", sa.Column("upload_quota_mb", sa.Integer(), server_default="500", nullable=False))

    for column in (
        sa.Column("visibility", sa.String(20), server_default="public", nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=True),
        sa.Column("maintainer_id", sa.String(36), nullable=True),
        sa.Column("analysis_progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("unresolved_feedback_count", sa.Integer(), server_default="0", nullable=False),
    ):
        op.add_column("works", column)

    for column in (
        sa.Column("translator", sa.String(200), nullable=True),
        sa.Column("visibility", sa.String(20), server_default="private", nullable=False),
        sa.Column("maintainer_id", sa.String(36), nullable=True),
        sa.Column("is_available", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("rights_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default="1", nullable=False),
    ):
        op.add_column("editions", column)

    for column in (
        sa.Column("visibility", sa.String(20), server_default="pending", nullable=False),
        sa.Column("detected_author", sa.String(300), nullable=True),
        sa.Column("publisher", sa.String(200), nullable=True),
        sa.Column("translator", sa.String(200), nullable=True),
        sa.Column("isbn", sa.String(32), nullable=True),
        sa.Column("rights_confirmed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("work_id", sa.String(36), nullable=True),
        sa.Column("edition_id", sa.String(36), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("book_imports", column)

    op.add_column("private_library_books", sa.Column("import_id", sa.String(36), nullable=True))
    op.add_column(
        "private_library_books",
        sa.Column("kind", sa.String(32), server_default="private_upload", nullable=False),
    )

    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("reporter_id", sa.String(36), nullable=False),
        sa.Column("assignee_id", sa.String(36), nullable=True),
        sa.Column("work_id", sa.String(36), nullable=True),
        sa.Column("edition_id", sa.String(36), nullable=True),
        sa.Column("entity_type", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("chapter", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("same_issue_count", sa.Integer(), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column("resolved_revision_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "content_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("work_id", sa.String(36), nullable=False),
        sa.Column("edition_id", sa.String(36), nullable=True),
        sa.Column("created_by", sa.String(36), nullable=True),
        sa.Column("source_feedback_id", sa.String(36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("work_id", "version", name="uq_revision_work_version"),
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("link", sa.String(500), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notifications")
    op.drop_table("content_revisions")
    op.drop_table("feedback")
    op.drop_column("private_library_books", "kind")
    op.drop_column("private_library_books", "import_id")
    for name in ("finalized_at", "edition_id", "work_id", "rights_confirmed", "isbn", "translator", "publisher", "detected_author", "visibility"):
        op.drop_column("book_imports", name)
    for name in ("revision", "rights_confirmed", "is_available", "maintainer_id", "visibility", "translator"):
        op.drop_column("editions", name)
    for name in ("unresolved_feedback_count", "analysis_progress", "maintainer_id", "owner_id", "visibility"):
        op.drop_column("works", name)
    for name in ("upload_quota_mb", "can_publish", "email_verified"):
        op.drop_column("users", name)
