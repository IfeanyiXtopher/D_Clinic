"""llm request audit

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-27 00:40:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("case_code", sa.String(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("purpose", sa.String(), nullable=False),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("prompt_version", sa.String(), nullable=False),
        sa.Column("packet_hash", sa.String(), nullable=False),
        sa.Column("deid_ok", sa.Boolean(), nullable=False),
        sa.Column("postcheck_ok", sa.Boolean(), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("refusal_reason", sa.String(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("case_code"),
    )
    op.create_index("index_llm_requests_on_patient_id", "llm_requests", ["patient_id"])
    op.create_index("index_llm_requests_on_created_at", "llm_requests", ["created_at"])


def downgrade() -> None:
    op.drop_index("index_llm_requests_on_created_at", table_name="llm_requests")
    op.drop_index("index_llm_requests_on_patient_id", table_name="llm_requests")
    op.drop_table("llm_requests")
