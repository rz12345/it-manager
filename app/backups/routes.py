import os

from flask import (abort, flash, redirect, render_template, request,
                   send_file, url_for)
from flask_login import current_user, login_required

from app import db
from app.backups import bp
from app.groups.decorators import admin_required, user_can_access
from app.models import BackupRecord, BackupRun, Device, Host


def _visible_runs_query():
    """依 current_user 可見範圍過濾 BackupRun。"""
    q = BackupRun.query
    if current_user.is_admin:
        return q

    host_ids = [h.id for h in Host.query.filter(
        Host.group_id.in_(current_user.group_ids or [0])
    ).all()]
    device_ids = [d.id for d in Device.query.filter(
        Device.group_id.in_(current_user.group_ids or [0])
    ).all()]

    return q.filter(
        db.or_(
            db.and_(BackupRun.target_type == 'host',
                    BackupRun.host_id.in_(host_ids or [0])),
            db.and_(BackupRun.target_type == 'device',
                    BackupRun.device_id.in_(device_ids or [0])),
        )
    )


# ── 備份歷史列表（全局） ──
@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    target_type = request.args.get('type', '').strip()
    status = request.args.get('status', '').strip()
    task_id = request.args.get('task_id', type=int)

    q = _visible_runs_query()
    if target_type in ('host', 'device'):
        q = q.filter(BackupRun.target_type == target_type)
    if status in ('running', 'success', 'partial', 'failed'):
        q = q.filter(BackupRun.status == status)
    if task_id:
        q = q.filter(BackupRun.task_id == task_id)

    pagination = q.order_by(BackupRun.started_at.desc()).paginate(
        page=page, per_page=30, error_out=False)

    return render_template('backups/list.html',
                           pagination=pagination,
                           filter_type=target_type,
                           filter_status=status,
                           filter_task_id=task_id)


# ── 單一主機／設備的備份歷史 ──
@bp.route('/host/<int:host_id>')
@login_required
def host_history(host_id):
    host = Host.query.get_or_404(host_id)
    if not user_can_access(host):
        abort(403)
    runs = BackupRun.query.filter_by(target_type='host', host_id=host.id) \
        .order_by(BackupRun.started_at.desc()).all()
    return render_template('backups/history.html',
                           target=host, target_type='host', runs=runs)


@bp.route('/device/<int:device_id>')
@login_required
def device_history(device_id):
    device = Device.query.get_or_404(device_id)
    if not user_can_access(device):
        abort(403)
    runs = BackupRun.query.filter_by(target_type='device', device_id=device.id) \
        .order_by(BackupRun.started_at.desc()).all()
    return render_template('backups/history.html',
                           target=device, target_type='device', runs=runs)


# ── 刪除特定備份版本 ──
@bp.route('/run/<int:run_id>/delete', methods=['POST'])
@admin_required
def delete_run(run_id):
    run = BackupRun.query.get_or_404(run_id)

    for rec in run.records:
        if rec.storage_path and os.path.exists(rec.storage_path):
            try:
                os.remove(rec.storage_path)
            except OSError:
                pass

    target_type = run.target_type
    host_id = run.host_id
    device_id = run.device_id

    db.session.delete(run)
    db.session.commit()
    flash('已刪除該次備份版本（含實體檔案）', 'info')

    if target_type == 'host' and host_id:
        return redirect(url_for('backups.host_history', host_id=host_id))
    if target_type == 'device' and device_id:
        return redirect(url_for('backups.device_history', device_id=device_id))
    return redirect(url_for('backups.index'))


# ── 下載單一備份檔案 ──
@bp.route('/record/<int:record_id>/download')
@login_required
def download_record(record_id):
    rec = BackupRecord.query.get_or_404(record_id)
    run = rec.run

    if run.target_type == 'host' and run.host_id:
        if not user_can_access(run.host):
            abort(403)
    elif run.target_type == 'device' and run.device_id:
        if not user_can_access(run.device):
            abort(403)

    if not rec.storage_path or not os.path.exists(rec.storage_path):
        abort(404)

    return send_file(rec.storage_path,
                     as_attachment=True,
                     download_name=os.path.basename(rec.storage_path))


# ── 線上檢視單一備份檔案（純文字） ──
@bp.route('/record/<int:record_id>/view')
@login_required
def view_record(record_id):
    rec = BackupRecord.query.get_or_404(record_id)
    run = rec.run

    if run.target_type == 'host' and run.host_id:
        if not user_can_access(run.host):
            abort(403)
    elif run.target_type == 'device' and run.device_id:
        if not user_can_access(run.device):
            abort(403)

    if not rec.storage_path or not os.path.exists(rec.storage_path):
        abort(404)

    return send_file(rec.storage_path,
                     mimetype='text/plain; charset=utf-8',
                     as_attachment=False,
                     download_name=os.path.basename(rec.storage_path))
