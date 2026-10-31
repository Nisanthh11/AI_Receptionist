"""Add user_id and notification status fields to appointments table

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('sms_status', sa.String(length=20), nullable=True))
        batch_op.add_column(sa.Column('email_status', sa.String(length=20), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f('fk_appointments_user_id_users'),
            'users',
            ['user_id'],
            ['id'],
            ondelete='SET NULL'
        )
        batch_op.create_index(batch_op.f('ix_appointments_user_id'), ['user_id'], unique=False)

    # Ensure 'user' role exists in roles table
    bind = op.get_bind()
    roles_table = sa.table(
        'roles',
        sa.column('name', sa.String),
        sa.column('description', sa.String)
    )
    existing_user_role = bind.execute(
        sa.select(roles_table.c.name).where(roles_table.c.name == 'user')
    ).scalar_one_or_none()
    if not existing_user_role:
        op.bulk_insert(roles_table, [{'name': 'user', 'description': 'Registered visitor'}])


def downgrade() -> None:
    with op.batch_alter_table('appointments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_appointments_user_id'))
        batch_op.drop_constraint(batch_op.f('fk_appointments_user_id_users'), type_='foreignkey')
        batch_op.drop_column('email_status')
        batch_op.drop_column('sms_status')
        batch_op.drop_column('user_id')
