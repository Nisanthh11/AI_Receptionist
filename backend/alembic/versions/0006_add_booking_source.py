"""Add booking_source column to appointments table

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-28
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('booking_source', sa.String(length=20), server_default='website', nullable=False))
    op.create_index(op.f('ix_appointments_booking_source'), 'appointments', ['booking_source'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_appointments_booking_source'), table_name='appointments')
    op.drop_column('appointments', 'booking_source')
