"""One-shot migration: legacy config-manager + task-manager → unified it-manager DB.

Reads two legacy sqlite files from backups/legacy/:
  - config_manager.db  (hosts/devices/backups/users/groups)
  - mail_scheduler.db  (email tasks/templates/scrapers/tags)

Inserts all data into the unified schema with id remapping. Config-manager wins
on username/app_setting key conflicts. Safe only against a freshly-migrated
(empty) target DB; aborts if target already has rows unless --force.

Usage:
    python -m scripts.migrate_legacy           # run
    python -m scripts.migrate_legacy --dry-run # report only
    python -m scripts.migrate_legacy --force   # overwrite non-empty target
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime


def _dt(val):
    if val is None or isinstance(val, datetime):
        return val
    try:
        return datetime.fromisoformat(val)
    except (TypeError, ValueError):
        return None


def _js(val):
    if val is None or not isinstance(val, str):
        return val
    try:
        return json.loads(val)
    except (TypeError, ValueError):
        return val

from app import create_app, db
from app.models import (
    AppSetting, Attachment, BackupRecord, BackupRun, BackupTask, Credential,
    Device, EmailRun, EmailTask, EmailTemplate, Group, Host, HostFilePath,
    HostTemplate, HostTemplatePath, LoginLog, Scraper, ScraperLog, Tag,
    TaskAlert, TaskTarget, TaskTemplate, User,
    scraper_tags, task_tags, template_tags, user_groups,
)

LEGACY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          'backups', 'legacy')
CM_PATH = os.path.join(LEGACY_DIR, 'config_manager.db')
MS_PATH = os.path.join(LEGACY_DIR, 'mail_scheduler.db')


def _open(path):
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _rows(conn, table):
    return conn.execute(f'SELECT * FROM "{table}"').fetchall()


def _not_empty_tables():
    """Return list of already-populated tables in the target DB (excluding alembic)."""
    populated = []
    for model in (User, Group, Host, Device, BackupTask, EmailTask, EmailTemplate, Scraper):
        if db.session.query(model).first() is not None:
            populated.append(model.__tablename__)
    return populated


def migrate(dry_run=False):
    if not os.path.exists(CM_PATH) or not os.path.exists(MS_PATH):
        print(f'ERROR: legacy DBs not found in {LEGACY_DIR}', file=sys.stderr)
        return 1
    cm = _open(CM_PATH)
    ms = _open(MS_PATH)

    report = []

    # ── USERS ──────────────────────────────────────────────────────────
    # config-manager wins: load its users first, then merge mail_scheduler users
    # by username (existing username → reuse id; else insert).
    user_map: dict[tuple[str, int], int] = {}
    for r in _rows(cm, 'users'):
        u = User(
            username=r['username'], email=r['email'] or '',
            password_hash=r['password_hash'], is_admin=bool(r['is_admin']),
            created_at=_dt(r['created_at']),
            password_changed_at=_dt(r['password_changed_at']),
        )
        db.session.add(u); db.session.flush()
        user_map[('cm', r['id'])] = u.id
    for r in _rows(ms, 'users'):
        existing = User.query.filter_by(username=r['username']).first()
        if existing:
            user_map[('ms', r['id'])] = existing.id
            continue
        u = User(
            username=r['username'], email=r['email'] or '',
            password_hash=r['password_hash'], is_admin=bool(r['is_admin']),
            created_at=_dt(r['created_at']),
            password_changed_at=_dt(r['password_changed_at']),
        )
        db.session.add(u); db.session.flush()
        user_map[('ms', r['id'])] = u.id
    report.append(f'users: {len(user_map)} mappings')

    # ── APP SETTINGS ──────────────────────────────────────────────────
    seen_keys: set[str] = set()
    kept = 0
    for r in _rows(cm, 'app_settings'):
        db.session.add(AppSetting(key=r['key'], value=r['value']))
        seen_keys.add(r['key']); kept += 1
    for r in _rows(ms, 'app_settings'):
        if r['key'] in seen_keys:
            continue
        db.session.add(AppSetting(key=r['key'], value=r['value']))
        seen_keys.add(r['key']); kept += 1
    report.append(f'app_settings: {kept}')

    # ── GROUPS + user_groups (config-manager only) ────────────────────
    group_map: dict[int, int] = {}
    for r in _rows(cm, 'groups'):
        g = Group(name=r['name'], description=r['description'], created_at=_dt(r['created_at']))
        db.session.add(g); db.session.flush()
        group_map[r['id']] = g.id
    for r in _rows(cm, 'user_groups'):
        uid = user_map.get(('cm', r['user_id']))
        gid = group_map.get(r['group_id'])
        if uid and gid:
            db.session.execute(user_groups.insert().values(user_id=uid, group_id=gid))
    report.append(f'groups: {len(group_map)}')

    # ── HOST TEMPLATES (+paths) ───────────────────────────────────────
    htmpl_map: dict[int, int] = {}
    for r in _rows(cm, 'host_templates'):
        t = HostTemplate(name=r['name'], description=r['description'],
                         created_at=_dt(r['created_at']))
        db.session.add(t); db.session.flush()
        htmpl_map[r['id']] = t.id
    for r in _rows(cm, 'host_template_paths'):
        new_tid = htmpl_map.get(r['template_id'])
        if new_tid:
            db.session.add(HostTemplatePath(template_id=new_tid, path=r['path']))
    report.append(f'host_templates: {len(htmpl_map)}')

    # ── CREDENTIALS (upsert dedup by username+password+enable) ────────
    cred_cache: dict[tuple[str, str, str], int] = {}
    cred_seq = [0]

    def _get_or_create_credential(username, password_enc, enable_password_enc):
        username = (username or '').strip() or 'unknown'
        password_enc = password_enc or ''
        enable_password_enc = enable_password_enc or ''
        key = (username, password_enc, enable_password_enc)
        if key in cred_cache:
            return cred_cache[key]
        cred_seq[0] += 1
        name = f'{username}@auto-{cred_seq[0]}'
        c = Credential(
            name=name, username=username,
            password_enc=password_enc,
            enable_password_enc=enable_password_enc,
            description='由舊資料匯入自動建立',
        )
        db.session.add(c); db.session.flush()
        cred_cache[key] = c.id
        return c.id

    # ── HOSTS + file paths ────────────────────────────────────────────
    host_map: dict[int, int] = {}
    for r in _rows(cm, 'hosts'):
        cid = _get_or_create_credential(r['username'], r['password_enc'], '')
        h = Host(
            name=r['name'], ip_address=r['ip_address'], port=r['port'],
            credential_id=cid,
            description=r['description'],
            group_id=group_map.get(r['group_id']) if r['group_id'] else None,
            is_active=bool(r['is_active']),
            created_at=_dt(r['created_at']), updated_at=_dt(r['updated_at']),
        )
        db.session.add(h); db.session.flush()
        host_map[r['id']] = h.id
    for r in _rows(cm, 'host_file_paths'):
        new_hid = host_map.get(r['host_id'])
        if new_hid:
            db.session.add(HostFilePath(host_id=new_hid, path=r['path'], source=r['source']))
    report.append(f'hosts: {len(host_map)}')

    # ── DEVICES ───────────────────────────────────────────────────────
    device_map: dict[int, int] = {}
    for r in _rows(cm, 'devices'):
        cid = _get_or_create_credential(
            r['username'], r['password_enc'], r['enable_password_enc'] or '')
        d = Device(
            name=r['name'], ip_address=r['ip_address'], port=r['port'],
            vendor=r['vendor'],
            credential_id=cid,
            backup_command=r['backup_command'], description=r['description'],
            group_id=group_map.get(r['group_id']) if r['group_id'] else None,
            is_active=bool(r['is_active']),
            created_at=_dt(r['created_at']), updated_at=_dt(r['updated_at']),
        )
        db.session.add(d); db.session.flush()
        device_map[r['id']] = d.id
    report.append(f'credentials: {len(cred_cache)}')
    report.append(f'devices: {len(device_map)}')

    # ── BACKUP TASKS + targets ────────────────────────────────────────
    btask_map: dict[int, int] = {}
    for r in _rows(cm, 'backup_tasks'):
        t = BackupTask(
            name=r['name'], description=r['description'],
            schedule_mode=r['schedule_mode'] or 'advanced',
            schedule_basic_params=_js(r['schedule_basic_params']),
            cron_expr=r['cron_expr'], scheduled_at=_dt(r['scheduled_at']),
            retain_count=r['retain_count'] or 10,
            is_active=bool(r['is_active']),
            next_run=_dt(r['next_run']), last_run=_dt(r['last_run']),
            last_status=r['last_status'],
            created_at=_dt(r['created_at']), updated_at=_dt(r['updated_at']),
        )
        db.session.add(t); db.session.flush()
        btask_map[r['id']] = t.id
    for r in _rows(cm, 'backup_task_targets'):
        new_tid = btask_map.get(r['task_id'])
        if not new_tid:
            continue
        db.session.add(TaskTarget(
            task_id=new_tid, target_type=r['target_type'],
            host_id=host_map.get(r['host_id']) if r['host_id'] else None,
            device_id=device_map.get(r['device_id']) if r['device_id'] else None,
        ))
    report.append(f'backup_tasks: {len(btask_map)}')

    # ── BACKUP RUNS + records + alerts ────────────────────────────────
    brun_map: dict[int, int] = {}
    for r in _rows(cm, 'backup_runs'):
        run = BackupRun(
            task_id=btask_map.get(r['task_id']) if r['task_id'] else None,
            target_type=r['target_type'],
            host_id=host_map.get(r['host_id']) if r['host_id'] else None,
            device_id=device_map.get(r['device_id']) if r['device_id'] else None,
            status=r['status'],
            file_count=r['file_count'] or 0,
            error_message=r['error_message'],
            triggered_by=r['triggered_by'] or 'schedule',
            started_at=_dt(r['started_at']), finished_at=_dt(r['finished_at']),
        )
        db.session.add(run); db.session.flush()
        brun_map[r['id']] = run.id
    for r in _rows(cm, 'backup_records'):
        new_rid = brun_map.get(r['run_id'])
        if new_rid:
            db.session.add(BackupRecord(
                run_id=new_rid, file_path=r['file_path'],
                storage_path=r['storage_path'], file_size=r['file_size'] or 0,
                checksum=r['checksum'], status=r['status'] or 'success',
                error_message=r['error_message'],
            ))
    for r in _rows(cm, 'backup_alerts'):
        new_rid = brun_map.get(r['run_id'])
        if new_rid:
            db.session.add(TaskAlert(
                run_id=new_rid, severity=r['severity'] or 'error',
                message=r['message'], is_read=bool(r['is_read']),
                created_at=_dt(r['created_at']),
            ))
    report.append(f'backup_runs: {len(brun_map)}')

    # ── LOGIN LOGS (both DBs) ─────────────────────────────────────────
    ll = 0
    for src, conn in (('cm', cm), ('ms', ms)):
        for r in _rows(conn, 'login_logs'):
            uid = user_map.get((src, r['user_id'])) if r['user_id'] else None
            db.session.add(LoginLog(
                user_id=uid, username=r['username'],
                ip_address=r['ip_address'], action=r['action'],
                status=r['status'], logged_at=_dt(r['logged_at']),
            ))
            ll += 1
    report.append(f'login_logs: {ll}')

    # ── EMAIL TEMPLATES + attachments ─────────────────────────────────
    etmpl_map: dict[int, int] = {}
    for r in _rows(ms, 'templates'):
        owner = user_map.get(('ms', r['owner_id']))
        t = EmailTemplate(
            name=r['name'], subject=r['subject'], body_path=r['body_path'],
            variables=_js(r['variables']), scraper_vars=_js(r['scraper_vars']),
            owner_id=owner,
            created_at=_dt(r['created_at']), updated_at=_dt(r['updated_at']),
        )
        db.session.add(t); db.session.flush()
        etmpl_map[r['id']] = t.id
    for r in _rows(ms, 'attachments'):
        new_tid = etmpl_map.get(r['template_id'])
        if new_tid:
            db.session.add(Attachment(
                template_id=new_tid, filename=r['filename'],
                storage_path=r['storage_path'], file_size=r['file_size'] or 0,
                mime_type=r['mime_type'], uploaded_at=_dt(r['uploaded_at']),
            ))
    report.append(f'email_templates: {len(etmpl_map)}')

    # ── SCRAPERS + logs ───────────────────────────────────────────────
    scr_map: dict[int, int] = {}
    for r in _rows(ms, 'scrapers'):
        s = Scraper(
            name=r['name'], url=r['url'],
            owner_id=user_map.get(('ms', r['owner_id'])),
            extract_type=r['extract_type'], extract_pattern=r['extract_pattern'],
            last_content=r['last_content'], last_checked=_dt(r['last_checked']),
            created_at=_dt(r['created_at']), updated_at=_dt(r['updated_at']),
        )
        db.session.add(s); db.session.flush()
        scr_map[r['id']] = s.id
    for r in _rows(ms, 'scraper_logs'):
        new_sid = scr_map.get(r['scraper_id'])
        if new_sid:
            db.session.add(ScraperLog(
                scraper_id=new_sid, status=r['status'],
                error_message=r['error_message'], checked_at=_dt(r['checked_at']),
                content=r['content'],
            ))
    report.append(f'scrapers: {len(scr_map)}')

    # ── TAGS (mail_scheduler only; per-owner) ─────────────────────────
    tag_map: dict[int, int] = {}
    for r in _rows(ms, 'tags'):
        t = Tag(
            name=r['name'], color=r['color'],
            owner_id=user_map.get(('ms', r['owner_id'])),
            created_at=_dt(r['created_at']),
        )
        db.session.add(t); db.session.flush()
        tag_map[r['id']] = t.id
    report.append(f'tags: {len(tag_map)}')

    # ── EMAIL TASKS + task_templates ──────────────────────────────────
    etask_map: dict[int, int] = {}
    for r in _rows(ms, 'tasks'):
        t = EmailTask(
            name=r['name'], description=r['description'],
            owner_id=user_map.get(('ms', r['owner_id'])),
            recipients=r['recipients'],
            schedule_mode=(r['schedule_mode']
                           or ('once' if r['schedule_type'] == 'once' else 'advanced')),
            schedule_basic_params=_js(r['schedule_basic_params']),
            cron_expr=r['cron_expr'], scheduled_at=_dt(r['scheduled_at']),
            next_run=_dt(r['next_run']),
            template_vars=_js(r['template_vars']),
            is_active=bool(r['is_active']),
            created_at=_dt(r['created_at']), updated_at=_dt(r['updated_at']),
        )
        db.session.add(t); db.session.flush()
        etask_map[r['id']] = t.id
    for r in _rows(ms, 'task_templates'):
        new_taskid = etask_map.get(r['task_id'])
        new_tmplid = etmpl_map.get(r['template_id'])
        if new_taskid and new_tmplid:
            db.session.add(TaskTemplate(
                task_id=new_taskid, template_id=new_tmplid, order=r['order'],
            ))
    report.append(f'email_tasks: {len(etask_map)}')

    # ── M2M TAG PIVOTS ────────────────────────────────────────────────
    def _pivot(rows, pivot_table, src_col, src_map):
        n = 0
        for r in rows:
            sid = src_map.get(r[src_col])
            tid = tag_map.get(r['tag_id'])
            if sid and tid:
                db.session.execute(pivot_table.insert().values(**{src_col: sid, 'tag_id': tid}))
                n += 1
        return n
    tt = _pivot(_rows(ms, 'task_tags'),     task_tags,     'task_id',     etask_map)
    mt = _pivot(_rows(ms, 'template_tags'), template_tags, 'template_id', etmpl_map)
    st = _pivot(_rows(ms, 'scraper_tags'),  scraper_tags,  'scraper_id',  scr_map)
    report.append(f'tag pivots: task={tt}, template={mt}, scraper={st}')

    # ── EMAIL RUNS (from send_logs) ───────────────────────────────────
    er = 0
    for r in _rows(ms, 'send_logs'):
        new_taskid = etask_map.get(r['task_id'])
        if not new_taskid:
            continue
        db.session.add(EmailRun(
            task_id=new_taskid, status=r['status'],
            recipients=r['recipients'], error_message=r['error_message'],
            started_at=_dt(r['sent_at']), finished_at=_dt(r['sent_at']),
            triggered_by='schedule',
        ))
        er += 1
    report.append(f'email_runs (from send_logs): {er}')

    if dry_run:
        db.session.rollback()
        print('[dry-run] rolled back. Would have migrated:')
    else:
        db.session.commit()
        print('committed. Migrated:')
    for line in report:
        print(f'  {line}')
    cm.close(); ms.close()
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true',
                    help='proceed even if target tables already have rows')
    args = ap.parse_args()

    app = create_app()
    with app.app_context():
        populated = _not_empty_tables()
        if populated and not args.force:
            print(f'ERROR: target DB already has data in: {", ".join(populated)}', file=sys.stderr)
            print('       pass --force to append (id remap still ensures no PK collision).',
                  file=sys.stderr)
            return 2
        return migrate(dry_run=args.dry_run)


if __name__ == '__main__':
    sys.exit(main())
