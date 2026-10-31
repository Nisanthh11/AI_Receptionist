"""Add persistent booking session columns to conversations table

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations', sa.Column('booking_state', sa.Text(), nullable=True))
    op.add_column('conversations', sa.Column('booking_step', sa.String(length=32), server_default='idle', nullable=True))
    op.add_column('conversations', sa.Column('expires_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_conversations_expires_at'), 'conversations', ['expires_at'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_conversations_expires_at'), table_name='conversations')
    op.drop_column('conversations', 'expires_at')
    op.drop_column('conversations', 'booking_step')
    op.drop_column('conversations', 'booking_state')
