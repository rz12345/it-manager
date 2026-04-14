"""資產頁：以分頁彙總 Linux 主機、網路設備、主機類型模板。"""
from flask import render_template, request
from flask_login import current_user, login_required

from app import db
from app.assets import bp
from app.models import Device, Host, HostTemplate


def _visible_hosts():
    q = Host.query
    if not current_user.is_admin:
        gids = current_user.group_ids
        if not gids:
            return []
        q = q.filter(Host.group_id.in_(gids))
    return q.order_by(Host.name).all()


def _visible_devices():
    q = Device.query
    if not current_user.is_admin:
        gids = current_user.group_ids
        if not gids:
            return []
        q = q.filter(Device.group_id.in_(gids))
    return q.order_by(Device.name).all()


@bp.route('/')
@login_required
def index():
    active_tab = request.args.get('tab', 'hosts')
    if active_tab not in ('hosts', 'devices', 'templates'):
        active_tab = 'hosts'
    if active_tab == 'templates' and not current_user.is_admin:
        active_tab = 'hosts'

    ctx = {'active_tab': active_tab}
    if active_tab == 'hosts':
        ctx['hosts'] = _visible_hosts()
    elif active_tab == 'devices':
        ctx['devices'] = _visible_devices()
    else:
        ctx['templates'] = HostTemplate.query.order_by(HostTemplate.name).all()
    return render_template('assets/index.html', **ctx)
