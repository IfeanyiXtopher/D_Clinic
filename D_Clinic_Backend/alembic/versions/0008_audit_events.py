"""audit_events for summary views, worklist changes, call results

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27 02:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("subject_type", sa.String(), nullable=True),
        sa.Column("subject_id", sa.String(), nullable=True),
        sa.Column("facility_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["facility_id"], ["facilities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "index_audit_events_on_action_and_created_at",
        "audit_events",
        ["action", "created_at"],
    )
    op.create_index(
        "index_audit_events_on_subject",
        "audit_events",
        ["subject_type", "subject_id"],
    )


def downgrade() -> None:
    op.drop_index("index_audit_events_on_subject", table_name="audit_events")
    op.drop_index("index_audit_events_on_action_and_created_at", table_name="audit_events")
    op.drop_table("audit_events")
