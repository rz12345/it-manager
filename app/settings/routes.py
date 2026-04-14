from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app import db
from app.auth.password_policy import validate_password
from app.groups.decorators import admin_required
from app.models import Device, Group, Host, LoginLog, User
from app.settings import bp
from app.settings.forms import (
    NotifyForm, PasswordPolicyForm, TimeoutForm, UserCreateForm,
)
from app.settings_store import get_setting, set_setting


_NOTIFY_KEYS = ('SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS',
                'SMTP_FROM', 'NOTIFY_EMAIL')
_TIMEOUT_KEYS = ('SSH_TIMEOUT_SECONDS', 'NETMIKO_TIMEOUT_SECONDS',
                 'SCHEDULER_MAX_WORKERS')
_PW_KEYS = ('PW_MIN_LENGTH', 'PW_MIN_UPPER', 'PW_MIN_LOWER',
            'PW_MIN_DIGIT', 'PW_MIN_SPECIAL', 'PW_EXPIRE_DAYS')


def _client_ip() -> str:
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or '-')


def _int_or(value, default):
    try:
        return int(value) if value not in (None, '') else default
    except (TypeError, ValueError):
        return default


@bp.route('/', methods=['GET', 'POST'])
@admin_required
def index():
    notify_form = NotifyForm()

    if notify_form.validate_on_submit():
        for key in _NOTIFY_KEYS:
            field = getattr(notify_form, key)
            if key == 'SMTP_PASS' and not field.data:
                continue  # 留白保留原值
            value = '' if field.data is None else str(field.data)
            set_setting(key, value)
        db.session.commit()
        flash('已儲存通知設定', 'success')
        return redirect(url_for('settings.index', tab='notify'))

    if not notify_form.is_submitted():
        notify_form.SMTP_HOST.data    = get_setting('SMTP_HOST', '')
        notify_form.SMTP_PORT.data    = _int_or(get_setting('SMTP_PORT'), 587)
        notify_form.SMTP_USER.data    = get_setting('SMTP_USER', '')
        notify_form.SMTP_FROM.data    = get_setting('SMTP_FROM', '')
        notify_form.NOTIFY_EMAIL.data = get_setting('NOTIFY_EMAIL', '')
        # SMTP_PASS 不回填

    timeout_form = TimeoutForm(prefix='timeout')
    if not timeout_form.is_submitted():
        timeout_form.SSH_TIMEOUT_SECONDS.data     = _int_or(get_setting('SSH_TIMEOUT_SECONDS'), 30)
        timeout_form.NETMIKO_TIMEOUT_SECONDS.data = _int_or(get_setting('NETMIKO_TIMEOUT_SECONDS'), 60)
        timeout_form.SCHEDULER_MAX_WORKERS.data   = _int_or(get_setting('SCHEDULER_MAX_WORKERS'), 5)

    pw_form = PasswordPolicyForm(prefix='pw')
    if not pw_form.is_submitted():
        pw_form.PW_MIN_LENGTH.data  = _int_or(get_setting('PW_MIN_LENGTH'),  8)
        pw_form.PW_MIN_UPPER.data   = _int_or(get_setting('PW_MIN_UPPER'),   0)
        pw_form.PW_MIN_LOWER.data   = _int_or(get_setting('PW_MIN_LOWER'),   0)
        pw_form.PW_MIN_DIGIT.data   = _int_or(get_setting('PW_MIN_DIGIT'),   0)
        pw_form.PW_MIN_SPECIAL.data = _int_or(get_setting('PW_MIN_SPECIAL'), 0)
        pw_form.PW_EXPIRE_DAYS.data = _int_or(get_setting('PW_EXPIRE_DAYS'), 0)

    has_smtp_pass = bool(get_setting('SMTP_PASS'))
    users = User.query.order_by(User.username).all()
    user_create_form = UserCreateForm(prefix='create')
    active_tab = request.args.get('tab', 'notify')

    # groups tab data
    groups_rows = None
    if active_tab == 'groups':
        from sqlalchemy import func
        groups = Group.query.order_by(Group.name).all()
        host_counts = dict(
            db.session.query(Host.group_id, func.count(Host.id))
            .group_by(Host.group_id).all()
        )
        device_counts = dict(
            db.session.query(Device.group_id, func.count(Device.id))
            .group_by(Device.group_id).all()
        )
        groups_rows = [{
            'group': g,
            'user_count': g.users.count(),
            'host_count': host_counts.get(g.id, 0),
            'device_count': device_counts.get(g.id, 0),
        } for g in groups]

    return render_template('settings/edit.html',
                           notify_form=notify_form,
                           timeout_form=timeout_form,
                           pw_form=pw_form,
                           user_create_form=user_create_form,
                           has_smtp_pass=has_smtp_pass,
                           users=users,
                           groups_rows=groups_rows,
                           active_tab=active_tab)


@bp.route('/test-email', methods=['POST'])
@admin_required
def test_email():
    from scheduler.notifier import send_email

    recipient = (get_setting('NOTIFY_EMAIL') or '').strip()
    if not recipient:
        flash('尚未設定「告警收件者 Email」，請先儲存後再測試。', 'warning')
        return redirect(url_for('settings.index', tab='notify'))

    ok, err = send_email(
        subject='[Config Manager] SMTP 測試信',
        body=(
            '這是一封 SMTP 測試信。\n\n'
            f'收件人：{recipient}\n'
            '如果您收到這封信，表示 SMTP 設定正確。'
        ),
        to_addr=recipient,
    )
    if ok:
        flash(f'測試信已寄出至 {recipient}', 'success')
    else:
        flash(f'測試寄送失敗：{err}', 'danger')
    return redirect(url_for('settings.index', tab='notify'))


@bp.route('/timeout', methods=['POST'])
@admin_required
def save_timeout():
    form = TimeoutForm(prefix='timeout')
    if form.validate_on_submit():
        for key in _TIMEOUT_KEYS:
            raw = getattr(form, key).data
            set_setting(key, str(int(raw)) if raw is not None else '')
        db.session.commit()
        flash('已儲存逾時設定', 'success')
    else:
        for field_errors in form.errors.values():
            for e in field_errors:
                flash(e, 'danger')
    return redirect(url_for('settings.index', tab='connection'))


@bp.route('/password-policy', methods=['POST'])
@admin_required
def save_password_policy():
    form = PasswordPolicyForm(prefix='pw')
    if form.validate_on_submit():
        for key in _PW_KEYS:
            raw = getattr(form, key).data
            set_setting(key, str(int(raw)) if raw is not None else '0')
        db.session.commit()
        flash('密碼規則已儲存', 'success')
    else:
        for field_errors in form.errors.values():
            for e in field_errors:
                flash(e, 'danger')
    return redirect(url_for('settings.index', tab='users'))


# ── 帳號管理（Admin 專用）──

@bp.route('/users/add', methods=['POST'])
@admin_required
def add_user():
    form = UserCreateForm(prefix='create')
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data.strip()).first():
            flash(f'帳號「{form.username.data}」已存在', 'danger')
            return redirect(url_for('settings.index', tab='users'))
        errors = validate_password(form.password.data)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return redirect(url_for('settings.index', tab='users'))
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip(),
            is_admin=form.is_admin.data,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'帳號「{user.username}」已建立', 'success')
    else:
        for field_errors in form.errors.values():
            for e in field_errors:
                flash(e, 'danger')
    return redirect(url_for('settings.index', tab='users'))


@bp.route('/users/<int:user_id>/edit', methods=['POST'])
@admin_required
def edit_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    email    = request.form.get('edit_email', '').strip()
    is_admin = request.form.get('edit_is_admin') == 'on'
    if not email:
        flash('Email 不可空白', 'danger')
        return redirect(url_for('settings.index', tab='users'))
    if user.id == current_user.id and not is_admin:
        flash('無法移除自己的管理者權限', 'danger')
        return redirect(url_for('settings.index', tab='users'))
    user.email    = email
    user.is_admin = is_admin
    db.session.commit()
    flash(f'帳號「{user.username}」已更新', 'success')
    return redirect(url_for('settings.index', tab='users'))


@bp.route('/users/<int:user_id>/delete', methods=['POST'])
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash('無法刪除目前登入的帳號', 'danger')
        return redirect(url_for('settings.index', tab='users'))
    db.session.delete(user)
    db.session.commit()
    flash(f'帳號「{user.username}」已刪除', 'success')
    return redirect(url_for('settings.index', tab='users'))


@bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@admin_required
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    new_password = request.form.get('reset_new_password', '')
    if not new_password:
        flash('新密碼不可空白', 'danger')
        return redirect(url_for('settings.index', tab='users'))
    errors = validate_password(new_password)
    if errors:
        for e in errors:
            flash(e, 'danger')
        return redirect(url_for('settings.index', tab='users'))
    user.set_password(new_password)
    db.session.add(LoginLog(
        user_id=user.id,
        username=user.username,
        ip_address=_client_ip(),
        action='password_reset',
        status='success',
    ))
    db.session.commit()
    flash(f'帳號「{user.username}」密碼已重設', 'success')
    return redirect(url_for('settings.index', tab='users'))
