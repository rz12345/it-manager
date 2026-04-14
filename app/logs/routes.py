from flask import render_template, request
from flask_login import current_user, login_required

from app.logs import bp
from app.models import LoginLog


@bp.route('/user-activity')
@login_required
def user_activity():
    page = request.args.get('page', 1, type=int)
    action = request.args.get('action', '').strip()
    status = request.args.get('status', '').strip()

    if current_user.is_admin:
        query = LoginLog.query
    else:
        query = LoginLog.query.filter_by(user_id=current_user.id)

    if action in ('login', 'logout', 'password_changed', 'password_reset'):
        query = query.filter_by(action=action)
    if status in ('success', 'failed'):
        query = query.filter_by(status=status)

    logs = query.order_by(LoginLog.logged_at.desc()).paginate(page=page, per_page=20)
    return render_template('logs/user_activity.html',
                           logs=logs,
                           selected_action=action,
                           selected_status=status)
