"""backup tasks: add BackupTask/BackupTaskTarget, drop per-Host/Device schedule fields

Revision ID: b1a7e2c9f4d0
Revises: 86aacfb3da11
Create Date: 2026-04-14 16:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b1a7e2c9f4d0'
down_revision = '86aacfb3da11'
branch_labels = None
depends_on = None


def upgrade():
    # ── 新表：backup_tasks ──
    op.create_table(
        'backup_tasks',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('schedule_mode', sa.String(length=10), nullable=False, server_default='advanced'),
        sa.Column('schedule_basic_params', sa.JSON(), nullable=True),
        sa.Column('cron_expr', sa.String(length=50), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('retain_count', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('next_run', sa.DateTime(), nullable=True),
        sa.Column('last_run', sa.DateTime(), nullable=True),
        sa.Column('last_status', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.UniqueConstraint('name'),
    )
    with op.batch_alter_table('backup_tasks') as b:
        b.create_index('ix_backup_tasks_is_active', ['is_active'])
        b.create_index('ix_backup_tasks_next_run', ['next_run'])

    # ── 新表：backup_task_targets ──
    op.create_table(
        'backup_task_targets',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('target_type', sa.String(length=10), nullable=False),
        sa.Column('host_id', sa.Integer(), nullable=True),
        sa.Column('device_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['backup_tasks.id']),
        sa.ForeignKeyConstraint(['host_id'], ['hosts.id']),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id']),
        sa.UniqueConstraint('task_id', 'host_id', name='uq_task_host'),
        sa.UniqueConstraint('task_id', 'device_id', name='uq_task_device'),
    )
    with op.batch_alter_table('backup_task_targets') as b:
        b.create_index('ix_backup_task_targets_task_id', ['task_id'])
        b.create_index('ix_backup_task_targets_host_id', ['host_id'])
        b.create_index('ix_backup_task_targets_device_id', ['device_id'])

    # ── backup_runs：新增 task_id ──
    with op.batch_alter_table('backup_runs') as b:
        b.add_column(sa.Column('task_id', sa.Integer(), nullable=True))
        b.create_index('ix_backup_runs_task_id', ['task_id'])
        b.create_foreign_key('fk_backup_runs_task_id', 'backup_tasks', ['task_id'], ['id'])

    # ── hosts：移除排程欄位 ──
    with op.batch_alter_table('hosts') as b:
        b.drop_index('ix_hosts_auto_backup_enabled')
        b.drop_index('ix_hosts_next_run')
        b.drop_column('auto_backup_enabled')
        b.drop_column('cron_expr')
        b.drop_column('retain_count')
        b.drop_column('next_run')
        b.drop_column('last_run')
        b.drop_column('last_status')

    # ── devices：移除排程欄位 ──
    with op.batch_alter_table('devices') as b:
        b.drop_index('ix_devices_auto_backup_enabled')
        b.drop_index('ix_devices_next_run')
        b.drop_column('auto_backup_enabled')
        b.drop_column('cron_expr')
        b.drop_column('retain_count')
        b.drop_column('next_run')
        b.drop_column('last_run')
        b.drop_column('last_status')


def downgrade():
    with op.batch_alter_table('devices') as b:
        b.add_column(sa.Column('last_status', sa.String(length=10), nullable=True))
        b.add_column(sa.Column('last_run', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('next_run', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('retain_count', sa.Integer(), nullable=False, server_default='10'))
        b.add_column(sa.Column('cron_expr', sa.String(length=50), nullable=True))
        b.add_column(sa.Column('auto_backup_enabled', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        b.create_index('ix_devices_next_run', ['next_run'])
        b.create_index('ix_devices_auto_backup_enabled', ['auto_backup_enabled'])

    with op.batch_alter_table('hosts') as b:
        b.add_column(sa.Column('last_status', sa.String(length=10), nullable=True))
        b.add_column(sa.Column('last_run', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('next_run', sa.DateTime(), nullable=True))
        b.add_column(sa.Column('retain_count', sa.Integer(), nullable=False, server_default='10'))
        b.add_column(sa.Column('cron_expr', sa.String(length=50), nullable=True))
        b.add_column(sa.Column('auto_backup_enabled', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        b.create_index('ix_hosts_next_run', ['next_run'])
        b.create_index('ix_hosts_auto_backup_enabled', ['auto_backup_enabled'])

    with op.batch_alter_table('backup_runs') as b:
        b.drop_constraint('fk_backup_runs_task_id', type_='foreignkey')
        b.drop_index('ix_backup_runs_task_id')
        b.drop_column('task_id')

    op.drop_table('backup_task_targets')
    op.drop_table('backup_tasks')
