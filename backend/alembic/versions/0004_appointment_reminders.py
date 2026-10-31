"""Add appointment reminders table

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'appointment_reminders',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('appointment_id', sa.Integer(), nullable=False),
        sa.Column('reminder_type', sa.String(length=20), nullable=False),
        sa.Column('scheduled_for', sa.DateTime(), nullable=False),
        sa.Column('appointment_start_at', sa.DateTime(), nullable=False),
        sa.Column('status', sa.String(length=20), server_default='pending', nullable=False),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('attempts', sa.Integer(), server_default='0', nullable=False),
        sa.Column('last_error', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['appointment_id'], ['appointments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('appointment_id', 'reminder_type', 'appointment_start_at', name='uq_appt_reminder_type_start'),
    )
    op.create_index(op.f('ix_appointment_reminders_appointment_id'), 'appointment_reminders', ['appointment_id'], unique=False)
    op.create_index(op.f('ix_appointment_reminders_scheduled_for'), 'appointment_reminders', ['scheduled_for'], unique=False)
    op.create_index(op.f('ix_appointment_reminders_status'), 'appointment_reminders', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_appointment_reminders_status'), table_name='appointment_reminders')
    op.drop_index(op.f('ix_appointment_reminders_scheduled_for'), table_name='appointment_reminders')
    op.drop_index(op.f('ix_appointment_reminders_appointment_id'), table_name='appointment_reminders')
    op.drop_table('appointment_reminders')
