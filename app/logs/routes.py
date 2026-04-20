from flask import redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.logs import bp
from app.models import (BackupRun, Device, EmailRun, Host, LoginLog, Task,
                        ToolRun)


def _visible_backup_runs_query():
    q = BackupRun.query
    if current_user.is_admin:
        return q
    gids = current_user.group_ids or [0]
    host_ids = [h.id for h in Host.query.filter(Host.group_id.in_(gids)).all()]
    device_ids = [d.id for d in Device.query.filter(Device.group_id.in_(gids)).all()]
    return q.filter(
        db.or_(
            db.and_(BackupRun.target_type == 'host',
                    BackupRun.host_id.in_(host_ids or [0])),
            db.and_(BackupRun.target_type == 'device',
                    BackupRun.device_id.in_(device_ids or [0])),
        )
    )


@bp.route('/')
@login_required
def index():
    tab = request.args.get('tab', 'backup')
    if tab not in ('backup', 'email', 'user', 'tool'):
        tab = 'backup'

    page = request.args.get('page', 1, type=int)
    ctx = {'active_log_tab': tab}

    if tab == 'backup':
        target_type = request.args.get('type', '').strip()
        status = request.args.get('status', '').strip()
        task_id = request.args.get('task_id', type=int)

        q = _visible_backup_runs_query()
        if target_type in ('host', 'device'):
            q = q.filter(BackupRun.target_type == target_type)
        if status in ('running', 'success', 'partial', 'failed'):
            q = q.filter(BackupRun.status == status)
        if task_id:
            q = q.filter(BackupRun.task_id == task_id)

        ctx['pagination'] = q.order_by(BackupRun.started_at.desc()).paginate(
            page=page, per_page=30, error_out=False)
        ctx['filter_type'] = target_type
        ctx['filter_status'] = status
        ctx['filter_task_id'] = task_id
        return render_template('logs/backup_runs.html', **ctx)

    if tab == 'email':
        status = request.args.get('status', '').strip()
        task_id = request.args.get('task_id', type=int)

        q = EmailRun.query.join(Task, EmailRun.task_id == Task.id)
        if not current_user.is_admin:
            q = q.filter(Task.owner_id == current_user.id)
        if status in ('success', 'partial', 'failed', 'running'):
            q = q.filter(EmailRun.status == status)
        if task_id:
            q = q.filter(EmailRun.task_id == task_id)

        ctx['runs'] = q.order_by(EmailRun.started_at.desc()).paginate(
            page=page, per_page=20, error_out=False)
        ctx['selected_status'] = status
        ctx['selected_task_id'] = task_id
        return render_template('logs/email_runs.html', **ctx)

    if tab == 'tool':
        tool_name = request.args.get('tool', '').strip()
        status = request.args.get('status', '').strip()

        if current_user.is_admin:
            q = ToolRun.query
        else:
            q = ToolRun.query.filter_by(user_id=current_user.id)
        if tool_name:
            q = q.filter(ToolRun.tool_name == tool_name)
        if status in ('running', 'success', 'not_found', 'failed'):
            q = q.filter(ToolRun.status == status)

        ctx['runs'] = q.order_by(ToolRun.started_at.desc()).paginate(
            page=page, per_page=20, error_out=False)
        ctx['selected_tool'] = tool_name
        ctx['selected_status'] = status
        return render_template('logs/tool_runs.html', **ctx)

    # tab == 'user'
    action = request.args.get('action', '').strip()
    status = request.args.get('status', '').strip()

    if current_user.is_admin:
        q = LoginLog.query
    else:
        q = LoginLog.query.filter_by(user_id=current_user.id)
    if action in ('login', 'logout', 'password_changed', 'password_reset'):
        q = q.filter_by(action=action)
    if status in ('success', 'failed'):
        q = q.filter_by(status=status)

    ctx['logs'] = q.order_by(LoginLog.logged_at.desc()).paginate(
        page=page, per_page=20, error_out=False)
    ctx['selected_action'] = action
    ctx['selected_status'] = status
    return render_template('logs/user_activity.html', **ctx)


# ── 向後相容：舊路由導向新 tab ──
@bp.route('/email-runs')
@login_required
def email_runs():
    return redirect(url_for('logs.index', tab='email', **request.args))


@bp.route('/user-activity')
@login_required
def user_activity():
    return redirect(url_for('logs.index', tab='user', **request.args))
