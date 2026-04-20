import json
import threading
from datetime import datetime, timezone

from flask import (abort, current_app, jsonify, render_template, request,
                   url_for)
from flask_login import current_user, login_required

from app import db
from app.groups.decorators import admin_required
from app.models import Device, ToolRun
from app.tools import bp
from app.tools.forms import MacTraceForm
from app.tools.mac_trace import SUPPORTED_VENDORS, run_mac_trace
from app.tools.mac_utils import normalize_mac


def _load_device_choices(form: MacTraceForm):
    q = (Device.query
         .filter(Device.is_active.is_(True),
                 Device.vendor.in_(SUPPORTED_VENDORS))
         .order_by(Device.name))
    if not current_user.is_admin:
        gids = current_user.group_ids or [0]
        q = q.filter(Device.group_id.in_(gids))
    devs = q.all()
    form.start_device_id.choices = [
        (d.id, f'{d.name} ({d.ip_address} · {d.vendor_label})') for d in devs
    ]


@bp.route('/')
@admin_required
def index():
    return render_template('tools/index.html')


@bp.route('/mac-trace', methods=['GET'])
@admin_required
def mac_trace_form():
    form = MacTraceForm()
    _load_device_choices(form)
    return render_template('tools/mac_trace.html', form=form)


@bp.route('/mac-trace/start', methods=['POST'])
@admin_required
def mac_trace_start():
    form = MacTraceForm()
    _load_device_choices(form)
    if not form.validate_on_submit():
        msg = _first_form_error(form) or '表單驗證失敗'
        return jsonify(ok=False, message=msg), 400

    try:
        mac12 = normalize_mac(form.mac.data)
    except ValueError as e:
        return jsonify(ok=False, message=str(e)), 400

    query = {
        'mac': mac12,
        'mac_raw': form.mac.data.strip(),
        'start_device_id': form.start_device_id.data,
        'max_hops': form.max_hops.data or 10,
    }
    run = ToolRun(
        tool_name='mac_trace',
        user_id=current_user.id,
        query_json=json.dumps(query, ensure_ascii=False),
        status='running',
        started_at=datetime.now(timezone.utc),
    )
    db.session.add(run)
    db.session.commit()

    run_id = run.id
    app_obj = current_app._get_current_object()

    def _background():
        with app_obj.app_context():
            try:
                run_mac_trace(run_id)
            except Exception:
                current_app.logger.exception('mac_trace background failed')

    threading.Thread(target=_background, daemon=True).start()
    return jsonify(ok=True, run_id=run_id,
                   status_url=url_for('tools.mac_trace_status', run_id=run_id),
                   detail_url=url_for('tools.mac_trace_detail', run_id=run_id))


@bp.route('/mac-trace/<int:run_id>/status')
@admin_required
def mac_trace_status(run_id):
    run = ToolRun.query.get_or_404(run_id)
    if run.tool_name != 'mac_trace':
        abort(404)
    payload = {
        'status': run.status,
        'finished': run.status != 'running',
        'error_message': run.error_message or '',
    }
    if payload['finished']:
        try:
            payload['result'] = json.loads(run.result_json or '{}')
        except json.JSONDecodeError:
            payload['result'] = {'hops': []}
        payload['query'] = (json.loads(run.query_json) if run.query_json else {})
    return jsonify(payload)


@bp.route('/mac-trace/<int:run_id>')
@login_required
def mac_trace_detail(run_id):
    run = ToolRun.query.get_or_404(run_id)
    if run.tool_name != 'mac_trace':
        abort(404)
    if not current_user.is_admin and run.user_id != current_user.id:
        abort(403)
    query = json.loads(run.query_json) if run.query_json else {}
    result = json.loads(run.result_json) if run.result_json else {}
    return render_template('tools/mac_trace_detail.html',
                           run=run, query=query, result=result)


def _first_form_error(form) -> str:
    for field in form:
        if field.errors:
            return f'{field.label.text}：{field.errors[0]}'
    return ''
