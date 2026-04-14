import shutil
from datetime import datetime, timedelta, timezone

from flask import current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.dashboard import bp
from app.groups.decorators import admin_required
from app.models import (BackupAlert, BackupRecord, BackupRun, BackupTask,
                        BackupTaskTarget, Device, Host)


def _storage_stats():
    """回傳備份磁碟與備份檔總量資訊。失敗時回 None。"""
    backup_base = current_app.config.get('BACKUP_BASE_PATH')
    if not backup_base:
        return None
    try:
        usage = shutil.disk_usage(backup_base)
    except (OSError, FileNotFoundError):
        return None

    backup_bytes = db.session.query(
        db.func.coalesce(db.func.sum(BackupRecord.file_size), 0)
    ).scalar() or 0

    used_pct = (usage.used / usage.total * 100) if usage.total else 0
    if used_pct >= 90:
        bar_class = 'bg-danger'
    elif used_pct >= 70:
        bar_class = 'bg-warning'
    else:
        bar_class = 'bg-success'

    return {
        'total': usage.total,
        'used': usage.used,
        'free': usage.free,
        'used_pct': round(used_pct, 1),
        'backup_bytes': int(backup_bytes),
        'bar_class': bar_class,
        'path': backup_base,
    }


def _visible_ids():
    if current_user.is_admin:
        return None, None
    gids = current_user.group_ids or [0]
    host_ids = [h.id for h in Host.query.filter(Host.group_id.in_(gids)).all()]
    device_ids = [d.id for d in Device.query.filter(Device.group_id.in_(gids)).all()]
    return host_ids, device_ids


def _visible_runs_query():
    q = BackupRun.query
    if current_user.is_admin:
        return q
    host_ids, device_ids = _visible_ids()
    return q.filter(
        db.or_(
            db.and_(BackupRun.target_type == 'host',
                    BackupRun.host_id.in_(host_ids or [0])),
            db.and_(BackupRun.target_type == 'device',
                    BackupRun.device_id.in_(device_ids or [0])),
        )
    )


def _visible_tasks_query():
    q = BackupTask.query
    if current_user.is_admin:
        return q
    host_ids, device_ids = _visible_ids()
    subq = (db.session.query(BackupTaskTarget.task_id)
            .filter(db.or_(
                db.and_(BackupTaskTarget.target_type == 'host',
                        BackupTaskTarget.host_id.in_(host_ids or [0])),
                db.and_(BackupTaskTarget.target_type == 'device',
                        BackupTaskTarget.device_id.in_(device_ids or [0])),
            )))
    return q.filter(BackupTask.id.in_(subq))


@bp.route('/')
@login_required
def index():
    host_ids, device_ids = _visible_ids()

    host_q = Host.query if current_user.is_admin else Host.query.filter(Host.id.in_(host_ids or [0]))
    device_q = Device.query if current_user.is_admin else Device.query.filter(Device.id.in_(device_ids or [0]))

    host_count = host_q.count()
    device_count = device_q.count()

    total_schedules = _visible_tasks_query().count()
    active_schedules = _visible_tasks_query().filter(BackupTask.is_active.is_(True)).count()

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(hours=24)
    runs_24h = _visible_runs_query().filter(BackupRun.started_at >= day_ago).count()
    success_24h = _visible_runs_query().filter(
        BackupRun.started_at >= day_ago,
        BackupRun.status == 'success',
    ).count()

    recent_runs = (_visible_runs_query()
                   .order_by(BackupRun.started_at.desc())
                   .limit(10).all())

    alerts_q = BackupAlert.query.join(BackupRun).filter(BackupAlert.is_read.is_(False))
    if not current_user.is_admin:
        alerts_q = alerts_q.filter(
            db.or_(
                db.and_(BackupRun.target_type == 'host',
                        BackupRun.host_id.in_(host_ids or [0])),
                db.and_(BackupRun.target_type == 'device',
                        BackupRun.device_id.in_(device_ids or [0])),
            )
        )
    alerts = alerts_q.order_by(BackupAlert.created_at.desc()).limit(20).all()

    upcoming_tasks = (_visible_tasks_query()
                      .filter(BackupTask.is_active.is_(True),
                              BackupTask.next_run.isnot(None))
                      .order_by(BackupTask.next_run.asc()).limit(10).all())

    storage = _storage_stats() if current_user.is_admin else None

    return render_template('dashboard/index.html',
                           host_count=host_count,
                           device_count=device_count,
                           active_schedules=active_schedules,
                           total_schedules=total_schedules,
                           runs_24h=runs_24h,
                           success_24h=success_24h,
                           recent_runs=recent_runs,
                           alerts=alerts,
                           upcoming_tasks=upcoming_tasks,
                           storage=storage)


@bp.route('/alerts/<int:alert_id>/read', methods=['POST'])
@login_required
def mark_alert_read(alert_id):
    alert = BackupAlert.query.get_or_404(alert_id)
    alert.is_read = True
    db.session.commit()
    return redirect(request.referrer or url_for('dashboard.index'))


@bp.route('/alerts/read-all', methods=['POST'])
@admin_required
def mark_all_alerts_read():
    BackupAlert.query.filter_by(is_read=False).update({'is_read': True})
    db.session.commit()
    flash('已標記所有告警為已讀', 'info')
    return redirect(url_for('dashboard.index'))
