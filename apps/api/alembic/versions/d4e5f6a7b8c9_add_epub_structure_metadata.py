"""add EPUB structure metadata

Revision ID: d4e5f6a7b8c9
Revises: b7a1c4d9e2f0
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "b7a1c4d9e2f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "editions",
        sa.Column("structure_version", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_editions_structure_version",
        "editions",
        ["structure_version"],
    )
    op.add_column(
        "analysis_jobs",
        sa.Column("structure_version", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_analysis_jobs_structure_version",
        "analysis_jobs",
        ["structure_version"],
    )
    op.add_column(
        "book_imports",
        sa.Column("language", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "book_imports",
        sa.Column("parser_version", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_book_imports_parser_version",
        "book_imports",
        ["parser_version"],
    )
    op.add_column(
        "book_imports",
        sa.Column("structure_version", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_book_imports_structure_version",
        "book_imports",
        ["structure_version"],
    )
    op.add_column(
        "book_imports",
        sa.Column("structure_source", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "book_imports",
        sa.Column(
            "structure_confidence",
            sa.String(length=20),
            server_default="low",
            nullable=False,
        ),
    )
    op.add_column(
        "book_imports",
        sa.Column(
            "structure_warnings",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "book_imports",
        sa.Column(
            "structure_tree",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
    )
    op.add_column(
        "book_imports",
        sa.Column(
            "structure_requires_review",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("book_imports", "structure_requires_review")
    op.drop_column("book_imports", "structure_tree")
    op.drop_column("book_imports", "structure_warnings")
    op.drop_column("book_imports", "structure_confidence")
    op.drop_column("book_imports", "structure_source")
    op.drop_index("ix_book_imports_structure_version", table_name="book_imports")
    op.drop_column("book_imports", "structure_version")
    op.drop_index("ix_book_imports_parser_version", table_name="book_imports")
    op.drop_column("book_imports", "parser_version")
    op.drop_column("book_imports", "language")
    op.drop_index("ix_analysis_jobs_structure_version", table_name="analysis_jobs")
    op.drop_column("analysis_jobs", "structure_version")
    op.drop_index("ix_editions_structure_version", table_name="editions")
    op.drop_column("editions", "structure_version")
