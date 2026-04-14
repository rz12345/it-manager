from datetime import datetime, timezone, timedelta

from flask import flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import OperationalError

from app import db
from app.auth import bp
from app.auth.forms import ChangePasswordForm, LoginForm, SetupForm
from app.auth.password_policy import get_policy, policy_description, validate_password
from app.models import LoginLog, User


def _client_ip() -> str:
    return (request.headers.get('X-Forwarded-For', '').split(',')[0].strip()
            or request.remote_addr or '-')


def _log(user_id, username: str, action: str, status: str):
    entry = LoginLog(
        user_id=user_id,
        username=username,
        ip_address=_client_ip(),
        action=action,
        status=status,
    )
    db.session.add(entry)
    db.session.commit()


def _has_users() -> bool:
    try:
        return User.query.count() > 0
    except OperationalError:
        return False


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not _has_users():
        return redirect(url_for('auth.setup'))
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))

    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=form.remember.data)
            _log(user.id, user.username, 'login', 'success')

            # 密碼到期檢查
            policy = get_policy()
            if policy['expire_days'] > 0 and user.password_changed_at:
                age = datetime.now(timezone.utc) - user.password_changed_at.replace(tzinfo=timezone.utc)
                if age > timedelta(days=policy['expire_days']):
                    session['pw_expired'] = True
                    flash('密碼已到期，請設定新密碼', 'warning')
                    return redirect(url_for('auth.change_password'))

            next_url = request.args.get('next')
            if next_url and next_url.startswith('/'):
                return redirect(next_url)
            return redirect(url_for('dashboard.index'))
        _log(None, form.username.data, 'login', 'failed')

        flash('帳號或密碼錯誤', 'danger')

    return render_template('auth/login.html', form=form)


@bp.route('/logout')
@login_required
def logout():
    username = current_user.username
    user_id = current_user.id
    logout_user()
    _log(user_id, username, 'logout', 'success')
    flash('已登出', 'info')
    return redirect(url_for('auth.login'))


@bp.route('/setup', methods=['GET', 'POST'])
def setup():
    if _has_users():
        return redirect(url_for('auth.login'))

    form = SetupForm()
    if form.validate_on_submit():
        errors = validate_password(form.password.data)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/setup.html', form=form)
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip(),
            is_admin=True,
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        _log(user.id, user.username, 'login', 'success')
        flash('管理者帳號建立成功', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/setup.html', form=form)


@bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    form = ChangePasswordForm()
    policy = get_policy()
    pw_hints = policy_description(policy)
    pw_expired = session.get('pw_expired', False)

    if form.validate_on_submit():
        if not current_user.check_password(form.current_password.data):
            flash('目前密碼不正確', 'danger')
            return render_template('auth/change_password.html', form=form,
                                   pw_hints=pw_hints, pw_expired=pw_expired)
        errors = validate_password(form.new_password.data)
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/change_password.html', form=form,
                                   pw_hints=pw_hints, pw_expired=pw_expired)
        current_user.set_password(form.new_password.data)
        db.session.commit()
        _log(current_user.id, current_user.username, 'password_changed', 'success')
        session.pop('pw_expired', None)
        flash('密碼已成功變更', 'success')
        return redirect(url_for('dashboard.index'))

    return render_template('auth/change_password.html', form=form,
                           pw_hints=pw_hints, pw_expired=pw_expired)
