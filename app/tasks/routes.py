import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import (abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import current_user, login_required

from app import db
from app.groups.decorators import admin_required, user_can_access
from app.models import (BackupRun, BackupTask, BackupTaskTarget, Device, Host)
from app.tasks import bp
from app.tasks.forms import BackupTaskForm


def _local_tz():
    return ZoneInfo(current_app.config.get('DISPLAY_TZ', 'Asia/Taipei'))


def _basic_to_cron(frequency, time_str, day=None, week=None):
    hh, mm = time_str.strip().split(':')
    if frequency == 'daily':
        return f'{int(mm)} {int(hh)} * * *'
    if frequency == 'monthly':
        suffix = 'L' if week == 'L' else f'#{week}'
        return f'{int(mm)} {int(hh)} * * {day}{suffix}'
    return f'{int(mm)} {int(hh)} * * {day}'


def _compute_next_run(task: BackupTask):
    if task.schedule_mode == 'once':
        return task.scheduled_at
    if not task.cron_expr:
        return None
    try:
        from croniter import croniter
        tz = _local_tz()
        now_local = datetime.now(tz)
        nxt_local = croniter(task.cron_expr.strip(), now_local).get_next(datetime)
        return nxt_local.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _load_choices(form: BackupTaskForm):
    if current_user.is_admin:
        hosts = Host.query.order_by(Host.name).all()
        devices = Device.query.order_by(Device.name).all()
    else:
        gids = current_user.group_ids or [0]
        hosts = Host.query.filter(Host.group_id.in_(gids)).order_by(Host.name).all()
        devices = Device.query.filter(Device.group_id.in_(gids)).order_by(Device.name).all()
    form.host_ids.choices = [(h.id, f'{h.name} ({h.ip_address})') for h in hosts]
    form.device_ids.choices = [(d.id, f'{d.name} ({d.vendor_label})') for d in devices]


def _user_can_access_task(task: BackupTask) -> bool:
    if current_user.is_admin:
        return True
    gids = set(current_user.group_ids or [])
    for t in task.targets:
        obj = t.target
        if obj is None or obj.group_id is None or obj.group_id not in gids:
            return False
    return True


def _visible_tasks_query():
    q = BackupTask.query
    if current_user.is_admin:
        return q
    gids = current_user.group_ids or [0]
    host_ids = {h.id for h in Host.query.filter(Host.group_id.in_(gids))}
    device_ids = {d.id for d in Device.query.filter(Device.group_id.in_(gids))}
    if not host_ids and not device_ids:
        return q.filter(db.false())
    subq = (db.session.query(BackupTaskTarget.task_id)
            .filter(db.or_(
                db.and_(BackupTaskTarget.target_type == 'host',
                        BackupTaskTarget.host_id.in_(host_ids or [0])),
                db.and_(BackupTaskTarget.target_type == 'device',
                        BackupTaskTarget.device_id.in_(device_ids or [0])),
            )))
    return q.filter(BackupTask.id.in_(subq))


def _save_targets(task: BackupTask, host_ids, device_ids):
    for t in list(task.targets):
        db.session.delete(t)
    db.session.flush()
    for hid in host_ids or []:
        db.session.add(BackupTaskTarget(task_id=task.id, target_type='host', host_id=hid))
    for did in device_ids or []:
        db.session.add(BackupTaskTarget(task_id=task.id, target_type='device', device_id=did))


def _apply_form_to_task(form: BackupTaskForm, task: BackupTask):
    mode = form.schedule_mode.data
    if mode == 'basic':
        freq = form.basic_frequency.data
        need_day = freq in ('weekly', 'monthly')
        task.cron_expr = _basic_to_cron(
            freq, form.basic_time.data,
            form.basic_day.data if need_day else None,
            form.basic_week.data if freq == 'monthly' else None,
        )
        task.scheduled_at = None
        task.schedule_basic_params = {
            'frequency': freq,
            'time': form.basic_time.data.strip(),
            'day': form.basic_day.data,
            'week': form.basic_week.data,
        }
    elif mode == 'advanced':
        task.cron_expr = form.cron_expr.data.strip()
        task.scheduled_at = None
        task.schedule_basic_params = None
    else:  # once
        task.cron_expr = None
        task.schedule_basic_params = None
        local_dt = form.scheduled_at.data
        task.scheduled_at = (local_dt.replace(tzinfo=_local_tz())
                             .astimezone(timezone.utc).replace(tzinfo=None))

    task.schedule_mode = mode
    task.name = form.name.data.strip()
    task.description = (form.description.data or '').strip() or None
    task.retain_count = form.retain_count.data or 10
    task.is_active = form.is_active.data
    task.next_run = _compute_next_run(task)


# ── 路由 ──
@bp.route('/')
@login_required
def index():
    tasks = _visible_tasks_query().order_by(BackupTask.name).all()
    return render_template('tasks/list.html', tasks=tasks)


@bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create():
    form = BackupTaskForm()
    _load_choices(form)
    if form.validate_on_submit():
        if BackupTask.query.filter_by(name=form.name.data.strip()).first():
            flash('任務名稱已存在', 'danger')
        else:
            task = BackupTask(name=form.name.data.strip())
            db.session.add(task)
            db.session.flush()
            _save_targets(task, form.host_ids.data, form.device_ids.data)
            _apply_form_to_task(form, task)
            db.session.commit()
            flash(f'已建立備份任務「{task.name}」', 'success')
            return redirect(url_for('tasks.detail', task_id=task.id))
    return render_template('tasks/create.html', form=form)


@bp.route('/<int:task_id>')
@login_required
def detail(task_id):
    task = BackupTask.query.get_or_404(task_id)
    if not _user_can_access_task(task):
        abort(403)
    return render_template('tasks/detail.html', task=task)


@bp.route('/<int:task_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit(task_id):
    task = BackupTask.query.get_or_404(task_id)
    form = BackupTaskForm(obj=task)
    _load_choices(form)

    if form.validate_on_submit():
        dup = BackupTask.query.filter(
            BackupTask.name == form.name.data.strip(),
            BackupTask.id != task.id).first()
        if dup:
            flash('任務名稱已存在', 'danger')
        else:
            _save_targets(task, form.host_ids.data, form.device_ids.data)
            _apply_form_to_task(form, task)
            db.session.commit()
            flash(f'已更新備份任務「{task.name}」', 'success')
            return redirect(url_for('tasks.detail', task_id=task.id))

    if request.method == 'GET':
        form.host_ids.data = task.host_ids
        form.device_ids.data = task.device_ids
        form.schedule_mode.data = task.schedule_mode or 'advanced'
        if task.scheduled_at:
            utc_dt = task.scheduled_at.replace(tzinfo=timezone.utc)
            form.scheduled_at.data = utc_dt.astimezone(_local_tz()).replace(tzinfo=None)
        if task.schedule_basic_params:
            bp_ = task.schedule_basic_params
            form.basic_frequency.data = bp_.get('frequency', 'daily')
            form.basic_time.data = bp_.get('time', '')
            form.basic_day.data = bp_.get('day', 1)
            form.basic_week.data = bp_.get('week', '1')

    return render_template('tasks/edit.html', form=form, task=task)


@bp.route('/<int:task_id>/delete', methods=['POST'])
@admin_required
def delete(task_id):
    task = BackupTask.query.get_or_404(task_id)
    name = task.name
    # 解除 BackupRun.task_id（保留歷史紀錄）
    task.backup_runs.update({BackupRun.task_id: None}, synchronize_session=False)
    db.session.delete(task)
    db.session.commit()
    flash(f'已刪除任務「{name}」', 'info')
    return redirect(url_for('tasks.index'))


@bp.route('/<int:task_id>/toggle', methods=['POST'])
@admin_required
def toggle(task_id):
    task = BackupTask.query.get_or_404(task_id)
    task.is_active = not task.is_active
    if not task.is_active:
        task.next_run = None
    else:
        task.next_run = _compute_next_run(task)
    db.session.commit()
    flash(f'任務已{"啟用" if task.is_active else "暫停"}', 'success')
    return redirect(url_for('tasks.detail', task_id=task.id))


@bp.route('/<int:task_id>/run', methods=['POST'])
@admin_required
def run_now(task_id):
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from app.settings_store import get_scheduler_max_workers

    try:
        task = BackupTask.query.get_or_404(task_id)
        try:
            from scheduler.ssh_backup import run_host_backup
            from scheduler.netmiko_backup import run_device_backup
        except ImportError:
            return jsonify(ok=False, message='排程器模組未安裝'), 501

        # 預先解析目標，避免子執行緒讀 lazy relationship
        plan = []
        for t in task.targets:
            if t.target_type == 'host' and t.host:
                plan.append(('host', t.host.id, t.target_name))
            elif t.target_type == 'device' and t.device:
                plan.append(('device', t.device.id, t.target_name))

        retain_count = task.retain_count
        task_id_val = task.id
        app_obj = current_app._get_current_object()

        def _worker(target_type, target_id, target_name):
            with app_obj.app_context():
                try:
                    if target_type == 'host':
                        r = run_host_backup(target_id, task_id=task_id_val,
                                            retain_count=retain_count,
                                            triggered_by='manual')
                    else:
                        r = run_device_backup(target_id, task_id=task_id_val,
                                              retain_count=retain_count,
                                              triggered_by='manual')
                    return (target_name, r.status, None)
                except Exception as e:
                    try: db.session.rollback()
                    except Exception: pass
                    return (target_name, 'error', str(e))

        success, failed = 0, 0
        messages = []
        workers = max(1, min(get_scheduler_max_workers(), len(plan) or 1))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(_worker, *p) for p in plan]
            for fut in as_completed(futures):
                name, status, err = fut.result()
                if status == 'success':
                    success += 1
                else:
                    failed += 1
                    messages.append(f'{name}: {err or status}')

        task.last_run = datetime.now(timezone.utc)
        task.last_status = 'success' if failed == 0 else ('partial' if success else 'failed')
        db.session.commit()

        msg = f'完成：成功 {success} / 失敗 {failed}'
        if messages:
            msg += '；' + '；'.join(messages[:3])
        return jsonify(ok=failed == 0, message=msg)
    except Exception as e:
        current_app.logger.exception('run_now failed')
        try: db.session.rollback()
        except Exception: pass
        return jsonify(ok=False, message=f'伺服器錯誤：{e}'), 500
