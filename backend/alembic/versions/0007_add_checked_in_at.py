"""Add checked_in_at column to appointments table

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('appointments', sa.Column('checked_in_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_appointments_checked_in_at'), 'appointments', ['checked_in_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_appointments_checked_in_at'), table_name='appointments')
    op.drop_column('appointments', 'checked_in_at')

