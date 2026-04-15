import os
import socket

from datetime import timezone
from zoneinfo import ZoneInfo

from flask import (abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import login_required

from app import db
from app.crypto import safe_decrypt
from app.devices import bp
from app.devices.forms import DeviceForm
from app.groups.decorators import admin_required, user_can_access
from app.models import (DEVICE_VENDORS, VENDOR_DEFAULT_COMMAND, BackupRecord,
                        BackupRun, Credential, Device, Group)
from app.settings_store import get_netmiko_timeout


def _load_form_choices(form: DeviceForm):
    groups = Group.query.order_by(Group.name).all()
    form.group_id.choices = [(0, '（未分組）')] + [(g.id, g.name) for g in groups]

    creds = Credential.query.order_by(Credential.name).all()
    form.credential_id.choices = (
        [(0, '（請選擇）')] + [(c.id, f'{c.name} ({c.username})') for c in creds]
    )


@bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create():
    form = DeviceForm()
    _load_form_choices(form)

    if form.validate_on_submit():
        if Device.query.filter_by(name=form.name.data.strip()).first():
            flash('設備名稱已存在', 'danger')
        elif form.vendor.data not in DEVICE_VENDORS:
            flash('不支援的廠商', 'danger')
        elif not form.credential_id.data or not Credential.query.get(form.credential_id.data):
            flash('請選擇有效的驗證', 'danger')
        else:
            device = Device(
                name=form.name.data.strip(),
                ip_address=form.ip_address.data.strip(),
                port=form.port.data or 22,
                vendor=form.vendor.data,
                credential_id=form.credential_id.data,
                backup_command=(form.backup_command.data or '').strip() or None,
                description=(form.description.data or '').strip(),
                group_id=(form.group_id.data or None) or None,
                is_active=form.is_active.data,
            )
            db.session.add(device)
            db.session.commit()
            flash(f'已建立設備「{device.name}」', 'success')
            return redirect(url_for('devices.detail', device_id=device.id))

    return render_template('devices/form.html', form=form, mode='create', device=None)


@bp.route('/<int:device_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit(device_id):
    device = Device.query.get_or_404(device_id)
    form = DeviceForm(obj=device)
    _load_form_choices(form)

    if request.method == 'GET':
        form.group_id.data = device.group_id or 0
        form.credential_id.data = device.credential_id

    if form.validate_on_submit():
        new_name = form.name.data.strip()
        dup = Device.query.filter(Device.name == new_name, Device.id != device.id).first()
        if dup:
            flash('設備名稱已存在', 'danger')
        elif form.vendor.data not in DEVICE_VENDORS:
            flash('不支援的廠商', 'danger')
        elif not form.credential_id.data or not Credential.query.get(form.credential_id.data):
            flash('請選擇有效的驗證', 'danger')
        else:
            device.name = new_name
            device.ip_address = form.ip_address.data.strip()
            device.port = form.port.data or 22
            device.vendor = form.vendor.data
            device.credential_id = form.credential_id.data
            device.backup_command = (form.backup_command.data or '').strip() or None
            device.description = (form.description.data or '').strip()
            device.group_id = form.group_id.data or None
            device.is_active = form.is_active.data
            db.session.commit()
            flash(f'已更新設備「{device.name}」', 'success')
            return redirect(url_for('devices.detail', device_id=device.id))

    return render_template('devices/form.html', form=form, mode='edit', device=device)


@bp.route('/<int:device_id>/delete', methods=['POST'])
@admin_required
def delete(device_id):
    device = Device.query.get_or_404(device_id)
    name = device.name
    db.session.delete(device)
    db.session.commit()
    flash(f'已刪除設備「{name}」', 'info')
    return redirect(url_for('assets.index', tab='devices'))


@bp.route('/<int:device_id>')
@login_required
def detail(device_id):
    device = Device.query.get_or_404(device_id)
    if not user_can_access(device):
        abort(403)

    tz = ZoneInfo(current_app.config.get('DISPLAY_TZ', 'Asia/Taipei'))
    runs = (BackupRun.query
            .filter_by(target_type='device', device_id=device.id)
            .filter(BackupRun.status.in_(('success', 'partial')))
            .order_by(BackupRun.started_at.desc())
            .all())
    daily_latest = []
    seen_days = set()
    for r in runs:
        started = r.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        day = started.astimezone(tz).date()
        if day in seen_days:
            continue
        seen_days.add(day)
        daily_latest.append((day, r))
        if len(daily_latest) >= 30:
            break

    return render_template('devices/detail.html', device=device,
                           vendor_default=VENDOR_DEFAULT_COMMAND.get(device.vendor, ''),
                           daily_latest=daily_latest)


@bp.route('/<int:device_id>/versions')
@login_required
def versions(device_id):
    device = Device.query.get_or_404(device_id)
    if not user_can_access(device):
        abort(403)

    tz = ZoneInfo(current_app.config.get('DISPLAY_TZ', 'Asia/Taipei'))
    records = (BackupRecord.query
               .join(BackupRun, BackupRecord.run_id == BackupRun.id)
               .filter(BackupRun.target_type == 'device',
                       BackupRun.device_id == device.id,
                       BackupRecord.status == 'success')
               .order_by(BackupRun.started_at.desc())
               .all())

    items = []
    for rec in records:
        if not rec.storage_path or not os.path.exists(rec.storage_path):
            continue
        started = rec.run.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        items.append({
            'id': rec.id,
            'file_path': rec.file_path,
            'started_at': started.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'),
            'size': rec.file_size,
            'checksum': rec.checksum or '',
        })
    return jsonify(ok=True, items=items)


@bp.route('/<int:device_id>/test-connection', methods=['POST'])
@admin_required
def test_connection(device_id):
    device = Device.query.get_or_404(device_id)
    timeout = get_netmiko_timeout()
    if device.credential is None:
        return jsonify(ok=False, message='設備未綁定驗證'), 400
    cred = device.credential
    username = cred.username
    password = safe_decrypt(cred.password_enc)
    enable_pw = safe_decrypt(cred.enable_password_enc) if cred.enable_password_enc else ''

    try:
        from netmiko import ConnectHandler
        from netmiko.exceptions import (NetmikoAuthenticationException,
                                        NetmikoTimeoutException)
    except ImportError:
        return jsonify(ok=False, message='伺服器未安裝 netmiko 套件'), 500

    params = {
        'device_type': device.vendor,
        'host': device.ip_address,
        'port': device.port,
        'username': username,
        'password': password,
        'conn_timeout': timeout,
        'fast_cli': False,
    }
    if enable_pw:
        params['secret'] = enable_pw

    conn = None
    try:
        conn = ConnectHandler(**params)
        prompt = conn.find_prompt()
        return jsonify(ok=True, message=f'連線成功（{prompt}）')
    except NetmikoAuthenticationException:
        return jsonify(ok=False, message='帳號或密碼錯誤')
    except NetmikoTimeoutException:
        return jsonify(ok=False, message=f'連線逾時（{timeout}s）')
    except socket.timeout:
        return jsonify(ok=False, message=f'連線逾時（{timeout}s）')
    except OSError as e:
        return jsonify(ok=False, message=f'網路錯誤：{e}')
    except Exception as e:
        return jsonify(ok=False, message=f'連線失敗：{e}')
    finally:
        if conn is not None:
            try:
                conn.disconnect()
            except Exception:
                pass
