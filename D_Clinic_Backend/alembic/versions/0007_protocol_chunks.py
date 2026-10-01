"""protocol chunks (text store; pgvector optional)

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-27 01:20:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "protocol_chunks",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    # Host PostgreSQL 18 may not have pgvector. The TF-IDF joblib index is
    # the retriever. When the extension exists, operators can add a vector column later.


def downgrade() -> None:
    op.drop_table("protocol_chunks")
