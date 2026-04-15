from flask import flash, redirect, render_template, url_for

from app import db
from app.credentials import bp
from app.credentials.forms import CredentialForm
from app.crypto import encrypt
from app.groups.decorators import admin_required
from app.models import Credential, Device, Host


def _render_list():
    """驗證庫列表（內嵌於 settings.index?tab=credentials 或直接 /credentials/）。"""
    credentials = Credential.query.order_by(Credential.name).all()
    rows = [{
        'cred': c,
        'host_count': c.hosts.count(),
        'device_count': c.devices.count(),
    } for c in credentials]
    return render_template('credentials/index.html', rows=rows)


@bp.route('/')
@admin_required
def index():
    # 保留舊 URL：重導向至設定頁驗證庫 tab
    return redirect(url_for('settings.index', tab='credentials'))


@bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create():
    form = CredentialForm()
    if form.validate_on_submit():
        name = form.name.data.strip()
        if Credential.query.filter_by(name=name).first():
            flash('驗證名稱已存在', 'danger')
        elif not form.password.data:
            flash('建立時密碼為必填', 'danger')
        else:
            cred = Credential(
                name=name,
                username=form.username.data.strip(),
                password_enc=encrypt(form.password.data),
                enable_password_enc=encrypt(form.enable_password.data or ''),
                description=(form.description.data or '').strip(),
            )
            db.session.add(cred)
            db.session.commit()
            flash(f'已建立驗證「{cred.name}」', 'success')
            return redirect(url_for('settings.index', tab='credentials'))
    return render_template('credentials/form.html', form=form, mode='create', cred=None)


@bp.route('/<int:cred_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit(cred_id):
    cred = Credential.query.get_or_404(cred_id)
    form = CredentialForm(obj=cred)
    if form.validate_on_submit():
        new_name = form.name.data.strip()
        dup = Credential.query.filter(Credential.name == new_name,
                                      Credential.id != cred.id).first()
        if dup:
            flash('驗證名稱已存在', 'danger')
        else:
            cred.name = new_name
            cred.username = form.username.data.strip()
            if form.password.data:
                cred.password_enc = encrypt(form.password.data)
            if form.enable_password.data:
                cred.enable_password_enc = encrypt(form.enable_password.data)
            cred.description = (form.description.data or '').strip()
            db.session.commit()
            flash(f'已更新驗證「{cred.name}」', 'success')
            return redirect(url_for('settings.index', tab='credentials'))
    if not form.is_submitted():
        form.password.data = ''
        form.enable_password.data = ''
    return render_template('credentials/form.html', form=form, mode='edit', cred=cred)


@bp.route('/<int:cred_id>/delete', methods=['POST'])
@admin_required
def delete(cred_id):
    cred = Credential.query.get_or_404(cred_id)
    host_cnt = Host.query.filter_by(credential_id=cred.id).count()
    device_cnt = Device.query.filter_by(credential_id=cred.id).count()
    if host_cnt or device_cnt:
        flash(
            f'無法刪除：驗證仍被 {host_cnt} 台主機、{device_cnt} 台設備引用，'
            '請先改用其他驗證。', 'danger'
        )
        return redirect(url_for('settings.index', tab='credentials'))
    name = cred.name
    db.session.delete(cred)
    db.session.commit()
    flash(f'已刪除驗證「{name}」', 'info')
    return redirect(url_for('settings.index', tab='credentials'))
