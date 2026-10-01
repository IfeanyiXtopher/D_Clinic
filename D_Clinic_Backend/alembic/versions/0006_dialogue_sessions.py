"""dialogue sessions and staff tasks

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-27 01:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dialogue_sessions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("appointment_id", sa.UUID(), nullable=True),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("offered_slots", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("pending_date", sa.Date(), nullable=True),
        sa.Column("visit_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["appointment_id"], ["appointments.id"]),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("index_dialogue_sessions_on_patient_id", "dialogue_sessions", ["patient_id"])
    op.create_table(
        "staff_tasks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("patient_id", sa.UUID(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["patient_id"], ["patients.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("index_staff_tasks_on_status", "staff_tasks", ["status"])


def downgrade() -> None:
    op.drop_index("index_staff_tasks_on_status", table_name="staff_tasks")
    op.drop_table("staff_tasks")
    op.drop_index("index_dialogue_sessions_on_patient_id", table_name="dialogue_sessions")
    op.drop_table("dialogue_sessions")
