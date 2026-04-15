"""add credential library

Revision ID: a1c0d11acred
Revises: 415065744b20
Create Date: 2026-04-15 12:00:00.000000

Creates the `credentials` table and migrates existing Host/Device credential
columns into it. Dedupes by (username, password_enc, enable_password_enc).
"""
from alembic import op
import sqlalchemy as sa
from datetime import datetime


# revision identifiers, used by Alembic.
revision = 'a1c0d11acred'
down_revision = '415065744b20'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # 1. create credentials table
    op.create_table(
        'credentials',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_enc', sa.Text(), nullable=False),
        sa.Column('enable_password_enc', sa.Text(), nullable=False),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # 2. add nullable credential_id on hosts & devices
    with op.batch_alter_table('hosts', schema=None) as batch:
        batch.add_column(sa.Column('credential_id', sa.Integer(), nullable=True))
        batch.create_index('ix_hosts_credential_id', ['credential_id'], unique=False)
        batch.create_foreign_key('fk_hosts_credential',
                                 'credentials', ['credential_id'], ['id'])

    with op.batch_alter_table('devices', schema=None) as batch:
        batch.add_column(sa.Column('credential_id', sa.Integer(), nullable=True))
        batch.create_index('ix_devices_credential_id', ['credential_id'], unique=False)
        batch.create_foreign_key('fk_devices_credential',
                                 'credentials', ['credential_id'], ['id'])

    # 3. data migration — upsert Credentials keyed on (username, pwd, enable)
    now = datetime.utcnow()
    # cache: (username, password_enc, enable_password_enc) -> credential_id
    cache: dict[tuple, int] = {}
    seq = [0]

    def _get_or_create(username, pwd, enable):
        username = (username or '').strip() or 'unknown'
        pwd = pwd or ''
        enable = enable or ''
        key = (username, pwd, enable)
        if key in cache:
            return cache[key]
        seq[0] += 1
        name = f'{username}@auto-{seq[0]}'
        result = bind.execute(sa.text(
            'INSERT INTO credentials (name, username, password_enc, '
            'enable_password_enc, description, created_at, updated_at) '
            'VALUES (:n, :u, :p, :e, :d, :t, :t)'
        ), {'n': name, 'u': username, 'p': pwd, 'e': enable,
            'd': '由舊資料自動歸併', 't': now})
        cid = result.lastrowid
        cache[key] = cid
        return cid

    # migrate hosts
    hosts = bind.execute(sa.text(
        'SELECT id, username, password_enc FROM hosts'
    )).fetchall()
    for row in hosts:
        cid = _get_or_create(row[1], row[2], '')
        bind.execute(sa.text('UPDATE hosts SET credential_id = :c WHERE id = :i'),
                     {'c': cid, 'i': row[0]})

    # migrate devices
    devices = bind.execute(sa.text(
        'SELECT id, username, password_enc, enable_password_enc FROM devices'
    )).fetchall()
    for row in devices:
        cid = _get_or_create(row[1], row[2], row[3] or '')
        bind.execute(sa.text('UPDATE devices SET credential_id = :c WHERE id = :i'),
                     {'c': cid, 'i': row[0]})

    # 4. make credential_id NOT NULL and drop legacy columns
    with op.batch_alter_table('hosts', schema=None) as batch:
        batch.alter_column('credential_id', existing_type=sa.Integer(), nullable=False)
        batch.drop_column('username')
        batch.drop_column('password_enc')

    with op.batch_alter_table('devices', schema=None) as batch:
        batch.alter_column('credential_id', existing_type=sa.Integer(), nullable=False)
        batch.drop_column('username')
        batch.drop_column('password_enc')
        batch.drop_column('enable_password_enc')


def downgrade():
    bind = op.get_bind()

    # 1. re-add legacy columns as nullable
    with op.batch_alter_table('hosts', schema=None) as batch:
        batch.add_column(sa.Column('username', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('password_enc', sa.Text(), nullable=True))

    with op.batch_alter_table('devices', schema=None) as batch:
        batch.add_column(sa.Column('username', sa.String(length=64), nullable=True))
        batch.add_column(sa.Column('password_enc', sa.Text(), nullable=True))
        batch.add_column(sa.Column('enable_password_enc', sa.Text(), nullable=True))

    # 2. copy back from credentials
    bind.execute(sa.text(
        'UPDATE hosts SET username = (SELECT username FROM credentials '
        'WHERE credentials.id = hosts.credential_id), '
        'password_enc = (SELECT password_enc FROM credentials '
        'WHERE credentials.id = hosts.credential_id)'
    ))
    bind.execute(sa.text(
        'UPDATE devices SET username = (SELECT username FROM credentials '
        'WHERE credentials.id = devices.credential_id), '
        'password_enc = (SELECT password_enc FROM credentials '
        'WHERE credentials.id = devices.credential_id), '
        'enable_password_enc = (SELECT enable_password_enc FROM credentials '
        'WHERE credentials.id = devices.credential_id)'
    ))

    # 3. enforce NOT NULL + drop FK / credential_id
    with op.batch_alter_table('hosts', schema=None) as batch:
        batch.alter_column('username', existing_type=sa.String(length=64), nullable=False)
        batch.alter_column('password_enc', existing_type=sa.Text(), nullable=False)
        batch.drop_constraint('fk_hosts_credential', type_='foreignkey')
        batch.drop_index('ix_hosts_credential_id')
        batch.drop_column('credential_id')

    with op.batch_alter_table('devices', schema=None) as batch:
        batch.alter_column('username', existing_type=sa.String(length=64), nullable=False)
        batch.alter_column('password_enc', existing_type=sa.Text(), nullable=False)
        batch.drop_constraint('fk_devices_credential', type_='foreignkey')
        batch.drop_index('ix_devices_credential_id')
        batch.drop_column('credential_id')

    # 4. drop credentials
    op.drop_table('credentials')
