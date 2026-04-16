import os
import socket
from datetime import timezone
from zoneinfo import ZoneInfo

from flask import (abort, current_app, flash, jsonify, redirect,
                   render_template, request, url_for)
from flask_login import login_required

from app import db
from app.crypto import safe_decrypt
from app.groups.decorators import admin_required, user_can_access
from app.hosts import bp
from app.hosts.forms import (HostFilePathForm, HostForm, HostTemplateForm,
                             HostTemplatePathForm)
from app.models import (BackupRecord, BackupRun, Credential, Group, Host,
                        HostFilePath, HostTemplate, HostTemplatePath)
from app.settings_store import get_ssh_timeout


# ── 選項載入 ──
def _load_form_choices(form: HostForm):
    groups = Group.query.order_by(Group.name).all()
    form.group_id.choices = [(0, '（未分組）')] + [(g.id, g.name) for g in groups]

    templates = HostTemplate.query.order_by(HostTemplate.name).all()
    form.template_id.choices = [(0, '（不套用）')] + [(t.id, t.name) for t in templates]

    creds = Credential.query.order_by(Credential.name).all()
    form.credential_id.choices = (
        [(0, '（請選擇）')] + [(c.id, f'{c.name} ({c.username})') for c in creds]
    )


def _apply_template(host: Host, template_id: int):
    """將模板路徑展開為 HostFilePath（source='template'），不覆蓋既有手動路徑。"""
    template = HostTemplate.query.get(template_id)
    if template is None:
        return
    existing = {(fp.path, fp.mode) for fp in host.file_paths}
    for tp in template.template_paths:
        if (tp.path, tp.mode) in existing:
            continue
        host.file_paths.append(HostFilePath(path=tp.path, mode=tp.mode, source='template'))


# ── 新增 ──
@bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create():
    form = HostForm()
    _load_form_choices(form)

    if form.validate_on_submit():
        if Host.query.filter_by(name=form.name.data.strip()).first():
            flash('主機名稱已存在', 'danger')
        elif not form.credential_id.data or not Credential.query.get(form.credential_id.data):
            flash('請選擇有效的驗證', 'danger')
        else:
            host = Host(
                name=form.name.data.strip(),
                ip_address=form.ip_address.data.strip(),
                port=form.port.data or 22,
                credential_id=form.credential_id.data,
                description=(form.description.data or '').strip(),
                group_id=(form.group_id.data or None) or None,
                is_active=form.is_active.data,
            )
            db.session.add(host)
            if form.template_id.data:
                _apply_template(host, form.template_id.data)
            db.session.commit()
            flash(f'已建立主機「{host.name}」', 'success')
            return redirect(url_for('hosts.detail', host_id=host.id))

    return render_template('hosts/form.html', form=form, mode='create', host=None)


# ── 編輯 ──
@bp.route('/<int:host_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit(host_id):
    host = Host.query.get_or_404(host_id)
    form = HostForm(obj=host)
    _load_form_choices(form)

    if request.method == 'GET':
        form.group_id.data = host.group_id or 0
        form.template_id.data = 0
        form.credential_id.data = host.credential_id

    if form.validate_on_submit():
        new_name = form.name.data.strip()
        dup = Host.query.filter(Host.name == new_name, Host.id != host.id).first()
        if dup:
            flash('主機名稱已存在', 'danger')
        elif not form.credential_id.data or not Credential.query.get(form.credential_id.data):
            flash('請選擇有效的驗證', 'danger')
        else:
            host.name = new_name
            host.ip_address = form.ip_address.data.strip()
            host.port = form.port.data or 22
            host.credential_id = form.credential_id.data
            host.description = (form.description.data or '').strip()
            host.group_id = form.group_id.data or None
            host.is_active = form.is_active.data
            if form.template_id.data:
                _apply_template(host, form.template_id.data)
            db.session.commit()
            flash(f'已更新主機「{host.name}」', 'success')
            return redirect(url_for('hosts.detail', host_id=host.id))

    return render_template('hosts/form.html', form=form, mode='edit', host=host)


# ── 刪除 ──
@bp.route('/<int:host_id>/delete', methods=['POST'])
@admin_required
def delete(host_id):
    host = Host.query.get_or_404(host_id)
    name = host.name
    db.session.delete(host)
    db.session.commit()
    flash(f'已刪除主機「{name}」', 'info')
    return redirect(url_for('assets.index', tab='hosts'))


# ── 詳細頁 ──
@bp.route('/<int:host_id>')
@login_required
def detail(host_id):
    host = Host.query.get_or_404(host_id)
    if not user_can_access(host):
        abort(403)
    path_form = HostFilePathForm()

    tz = ZoneInfo(current_app.config.get('DISPLAY_TZ', 'Asia/Taipei'))
    runs = (BackupRun.query
            .filter_by(target_type='host', host_id=host.id)
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

    return render_template('hosts/detail.html', host=host, path_form=path_form,
                           daily_latest=daily_latest)


# ── 備份路徑管理 ──
@bp.route('/<int:host_id>/paths/add', methods=['POST'])
@admin_required
def add_path(host_id):
    host = Host.query.get_or_404(host_id)
    form = HostFilePathForm()
    if form.validate_on_submit():
        path = form.path.data.strip()
        mode = form.mode.data or 'sftp'
        exists = any(fp.path == path and fp.mode == mode for fp in host.file_paths)
        if exists:
            flash('此路徑已存在', 'warning')
        else:
            host.file_paths.append(HostFilePath(path=path, mode=mode, source='manual'))
            db.session.commit()
            flash('已新增備份路徑', 'success')
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, 'danger')
    return redirect(url_for('hosts.detail', host_id=host.id))


@bp.route('/<int:host_id>/paths/<int:path_id>/delete', methods=['POST'])
@admin_required
def delete_path(host_id, path_id):
    host = Host.query.get_or_404(host_id)
    fp = HostFilePath.query.filter_by(id=path_id, host_id=host.id).first_or_404()
    db.session.delete(fp)
    db.session.commit()
    flash('已移除備份路徑', 'info')
    return redirect(url_for('hosts.detail', host_id=host.id))


# ── 備份版本清單（供差異比較 Modal 使用） ──
@bp.route('/<int:host_id>/versions')
@login_required
def versions(host_id):
    host = Host.query.get_or_404(host_id)
    if not user_can_access(host):
        abort(403)

    path = (request.args.get('path') or '').strip()
    tz = ZoneInfo(current_app.config.get('DISPLAY_TZ', 'Asia/Taipei'))

    q = (BackupRecord.query
         .join(BackupRun, BackupRecord.run_id == BackupRun.id)
         .filter(BackupRun.target_type == 'host',
                 BackupRun.host_id == host.id,
                 BackupRecord.status == 'success'))

    is_glob = False
    if path:
        is_glob = any(ch in path for ch in '*?[')
        if is_glob:
            like = path.replace('*', '%').replace('?', '_')
            q = q.filter(BackupRecord.file_path.like(like))
        else:
            q = q.filter(BackupRecord.file_path == path)

    records = q.order_by(BackupRun.started_at.desc()).all()

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
    return jsonify(ok=True, path=path, is_glob=is_glob, items=items)


# ── 測試 SSH 連線（AJAX） ──
@bp.route('/<int:host_id>/test-connection', methods=['POST'])
@admin_required
def test_connection(host_id):
    host = Host.query.get_or_404(host_id)
    timeout = get_ssh_timeout()
    if host.credential is None:
        return jsonify(ok=False, message='主機未綁定驗證'), 400
    password = safe_decrypt(host.credential.password_enc)
    username = host.credential.username

    try:
        import paramiko  # 延遲載入
    except ImportError:
        return jsonify(ok=False, message='伺服器未安裝 paramiko 套件'), 500

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=host.ip_address,
            port=host.port,
            username=username,
            password=password,
            timeout=timeout,
            allow_agent=False,
            look_for_keys=False,
        )
        transport = client.get_transport()
        banner = transport.remote_version if transport else ''
        client.close()
        return jsonify(ok=True, message=f'連線成功 ({banner})')
    except paramiko.AuthenticationException:
        return jsonify(ok=False, message='帳號或密碼錯誤')
    except paramiko.SSHException as e:
        return jsonify(ok=False, message=f'SSH 錯誤：{e}')
    except socket.timeout:
        return jsonify(ok=False, message=f'連線逾時（{timeout}s）')
    except OSError as e:
        return jsonify(ok=False, message=f'網路錯誤：{e}')
    except Exception as e:
        return jsonify(ok=False, message=f'連線失敗：{e}')
    finally:
        try:
            client.close()
        except Exception:
            pass


# ── 主機類型模板 CRUD（Admin 專用） ──
@bp.route('/templates/create', methods=['GET', 'POST'])
@admin_required
def templates_create():
    form = HostTemplateForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if HostTemplate.query.filter_by(name=name).first():
            flash('模板名稱已存在', 'danger')
        else:
            tpl = HostTemplate(
                name=name,
                description=(form.description.data or '').strip(),
            )
            db.session.add(tpl)
            db.session.commit()
            flash(f'已建立模板「{tpl.name}」', 'success')
            return redirect(url_for('hosts.templates_detail', template_id=tpl.id))
    return render_template('hosts/templates_form.html', form=form, mode='create', template=None)


@bp.route('/templates/<int:template_id>/edit', methods=['GET', 'POST'])
@admin_required
def templates_edit(template_id):
    tpl = HostTemplate.query.get_or_404(template_id)
    form = HostTemplateForm(obj=tpl)
    if form.validate_on_submit():
        new_name = form.name.data.strip()
        dup = HostTemplate.query.filter(HostTemplate.name == new_name,
                                        HostTemplate.id != tpl.id).first()
        if dup:
            flash('模板名稱已存在', 'danger')
        else:
            tpl.name = new_name
            tpl.description = (form.description.data or '').strip()
            db.session.commit()
            flash(f'已更新模板「{tpl.name}」', 'success')
            return redirect(url_for('hosts.templates_detail', template_id=tpl.id))
    return render_template('hosts/templates_form.html', form=form, mode='edit', template=tpl)


@bp.route('/templates/<int:template_id>')
@admin_required
def templates_detail(template_id):
    tpl = HostTemplate.query.get_or_404(template_id)
    path_form = HostTemplatePathForm()
    return render_template('hosts/templates_detail.html', template=tpl, path_form=path_form)


@bp.route('/templates/<int:template_id>/delete', methods=['POST'])
@admin_required
def templates_delete(template_id):
    tpl = HostTemplate.query.get_or_404(template_id)
    name = tpl.name
    db.session.delete(tpl)
    db.session.commit()
    flash(f'已刪除模板「{name}」', 'info')
    return redirect(url_for('assets.index', tab='templates'))


@bp.route('/templates/<int:template_id>/paths/add', methods=['POST'])
@admin_required
def templates_add_path(template_id):
    tpl = HostTemplate.query.get_or_404(template_id)
    form = HostTemplatePathForm()
    if form.validate_on_submit():
        path = form.path.data.strip()
        mode = form.mode.data or 'sftp'
        if any(tp.path == path and tp.mode == mode for tp in tpl.template_paths):
            flash('此路徑已存在', 'warning')
        else:
            tpl.template_paths.append(HostTemplatePath(path=path, mode=mode))
            db.session.commit()
            flash('已新增預設路徑', 'success')
    else:
        for errors in form.errors.values():
            for err in errors:
                flash(err, 'danger')
    return redirect(url_for('hosts.templates_detail', template_id=tpl.id))


@bp.route('/templates/<int:template_id>/paths/<int:path_id>/delete', methods=['POST'])
@admin_required
def templates_delete_path(template_id, path_id):
    tpl = HostTemplate.query.get_or_404(template_id)
    tp = HostTemplatePath.query.filter_by(id=path_id, template_id=tpl.id).first_or_404()
    db.session.delete(tp)
    db.session.commit()
    flash('已移除預設路徑', 'info')
    return redirect(url_for('hosts.templates_detail', template_id=tpl.id))
