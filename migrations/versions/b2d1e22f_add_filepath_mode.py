"""add mode column to host_file_paths and host_template_paths

Revision ID: b2d1e22fmode
Revises: a1c0d11acred
Create Date: 2026-04-16 10:30:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = 'b2d1e22fmode'
down_revision = 'a1c0d11acred'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('host_file_paths') as batch_op:
        batch_op.add_column(
            sa.Column('mode', sa.String(10), nullable=False, server_default='sftp'))

    with op.batch_alter_table('host_template_paths') as batch_op:
        batch_op.add_column(
            sa.Column('mode', sa.String(10), nullable=False, server_default='sftp'))


def downgrade():
    with op.batch_alter_table('host_template_paths') as batch_op:
        batch_op.drop_column('mode')

    with op.batch_alter_table('host_file_paths') as batch_op:
        batch_op.drop_column('mode')
