"""worklist items

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26 23:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('worklist_items',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('facility_id', sa.UUID(), nullable=False),
    sa.Column('list_date', sa.Date(), nullable=False),
    sa.Column('list_type', sa.String(), nullable=False),
    sa.Column('rank', sa.Integer(), nullable=False),
    sa.Column('patient_id', sa.UUID(), nullable=False),
    sa.Column('appointment_id', sa.UUID(), nullable=False),
    sa.Column('priority', sa.Numeric(precision=8, scale=4), nullable=True),
    sa.Column('p_missed', sa.Numeric(precision=6, scale=4), nullable=True),
    sa.Column('band', sa.String(), nullable=True),
    sa.Column('basis', sa.String(), nullable=True),
    sa.Column('days_overdue', sa.Integer(), nullable=False),
    sa.Column('uncontrolled', sa.Boolean(), nullable=False),
    sa.Column('protected_slot', sa.Boolean(), nullable=False),
    sa.Column('has_phone', sa.Boolean(), nullable=False),
    sa.Column('suggested_action', sa.String(), nullable=False),
    sa.Column('reasons', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('status', sa.String(), nullable=False),
    sa.Column('call_result_id', sa.UUID(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ),
    sa.ForeignKeyConstraint(['call_result_id'], ['call_results.id'], ),
    sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ),
    sa.ForeignKeyConstraint(['patient_id'], ['patients.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('facility_id', 'list_date', 'list_type', 'appointment_id', name='uq_worklist_items_day_appointment')
    )
    op.create_index('index_worklist_items_on_facility_id_and_list_date', 'worklist_items', ['facility_id', 'list_date'], unique=False)
    op.create_index('index_worklist_items_on_patient_id', 'worklist_items', ['patient_id'], unique=False)


def downgrade() -> None:
    op.drop_index('index_worklist_items_on_patient_id', table_name='worklist_items')
    op.drop_index('index_worklist_items_on_facility_id_and_list_date', table_name='worklist_items')
    op.drop_table('worklist_items')
