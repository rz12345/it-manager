"""差異比較：選取同一 Host/Device 任兩個備份版本，計算 unified diff。"""
from __future__ import annotations

import difflib
import os
from collections import OrderedDict

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.compare import bp
from app.groups.decorators import user_can_access
from app.models import BackupRecord, BackupRun, Device, Host


def _group_records_by_file(runs):
    """將 runs 的成功 records 依 file_path 分組，僅保留版本數 >=2 的檔案。
    回傳 OrderedDict[file_path] -> list[(record, run)]，依 file_path 字母排序，
    每組內依 run.started_at 由新到舊。"""
    groups = {}
    for run in runs:
        if run.status not in ('success', 'partial'):
            continue
        for rec in run.records:
            if rec.status != 'success':
                continue
            if not rec.storage_path or not os.path.exists(rec.storage_path):
                continue
            groups.setdefault(rec.file_path, []).append((rec, run))
    comparable = OrderedDict()
    for fp in sorted(groups.keys()):
        recs = groups[fp]
        if len(recs) >= 2:
            comparable[fp] = recs
    return comparable


def _visible_hosts():
    if current_user.is_admin:
        return Host.query.order_by(Host.name).all()
    ids = current_user.group_ids or [0]
    return Host.query.filter(Host.group_id.in_(ids)).order_by(Host.name).all()


def _visible_devices():
    if current_user.is_admin:
        return Device.query.order_by(Device.name).all()
    ids = current_user.group_ids or [0]
    return Device.query.filter(Device.group_id.in_(ids)).order_by(Device.name).all()


@bp.route('/')
@login_required
def index():
    return render_template('compare/index.html',
                           hosts=_visible_hosts(),
                           devices=_visible_devices())


@bp.route('/host/<int:host_id>')
@login_required
def select_host(host_id):
    host = Host.query.get_or_404(host_id)
    if not user_can_access(host):
        abort(403)
    runs = (BackupRun.query
            .filter_by(target_type='host', host_id=host.id)
            .order_by(BackupRun.started_at.desc())
            .all())
    groups = _group_records_by_file(runs)
    return render_template('compare/select.html',
                           target=host, target_type='host',
                           groups=groups)


@bp.route('/device/<int:device_id>')
@login_required
def select_device(device_id):
    device = Device.query.get_or_404(device_id)
    if not user_can_access(device):
        abort(403)
    runs = (BackupRun.query
            .filter_by(target_type='device', device_id=device.id)
            .order_by(BackupRun.started_at.desc())
            .all())
    groups = _group_records_by_file(runs)
    return render_template('compare/select.html',
                           target=device, target_type='device',
                           groups=groups)


def _read_record(rec: BackupRecord) -> str:
    if not rec.storage_path or not os.path.exists(rec.storage_path):
        return ''
    try:
        with open(rec.storage_path, 'r', encoding='utf-8', errors='replace') as fh:
            return fh.read()
    except OSError:
        return ''


@bp.route('/view')
@login_required
def view():
    left_id = request.args.get('left', type=int)
    right_id = request.args.get('right', type=int)
    if not left_id or not right_id:
        flash('請選擇兩個版本進行比較', 'warning')
        return redirect(url_for('compare.index'))
    if left_id == right_id:
        flash('請選擇不同的兩個版本', 'warning')
        return redirect(url_for('compare.index'))

    left = BackupRecord.query.get_or_404(left_id)
    right = BackupRecord.query.get_or_404(right_id)

    # 權限檢查（兩端皆須可存取，且屬於同一目標）
    def _guard(rec):
        run = rec.run
        if run.target_type == 'host' and run.host and not user_can_access(run.host):
            abort(403)
        if run.target_type == 'device' and run.device and not user_can_access(run.device):
            abort(403)

    _guard(left)
    _guard(right)

    lrun, rrun = left.run, right.run
    if lrun.target_type != rrun.target_type or \
       (lrun.host_id or 0) != (rrun.host_id or 0) or \
       (lrun.device_id or 0) != (rrun.device_id or 0):
        flash('僅能比較同一主機/設備的版本', 'danger')
        return redirect(url_for('compare.index'))

    left_text = _read_record(left)
    right_text = _read_record(right)

    left_label = f'{left.file_path} @ {lrun.started_at.strftime("%Y-%m-%d %H:%M:%S")}'
    right_label = f'{right.file_path} @ {rrun.started_at.strftime("%Y-%m-%d %H:%M:%S")}'

    diff_text = ''.join(difflib.unified_diff(
        left_text.splitlines(keepends=True),
        right_text.splitlines(keepends=True),
        fromfile=left_label,
        tofile=right_label,
    ))

    target = lrun.host if lrun.target_type == 'host' else lrun.device

    return render_template('compare/view.html',
                           target=target,
                           target_type=lrun.target_type,
                           left=left, right=right,
                           left_label=left_label, right_label=right_label,
                           diff_text=diff_text)
