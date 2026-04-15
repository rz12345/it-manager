import json
import os
import shutil
import uuid

from flask import abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required

from app import db
from app.config import Config
from app.models import Attachment, EmailTemplate, Scraper, Tag, _tag_color, template_tags
from app.templates_mgr import bp
from app.templates_mgr.forms import TemplateForm


def _parse_tags(tag_str, owner_id):
    names = [n.strip() for n in tag_str.split(',') if n.strip()]
    tags = []
    for name in names:
        tag = Tag.query.filter_by(name=name, owner_id=owner_id).first()
        if not tag:
            tag = Tag(name=name, color=_tag_color(name), owner_id=owner_id)
            db.session.add(tag)
        tags.append(tag)
    return tags


def _scraper_choices():
    return [(s.id, s.name) for s in Scraper.query.filter_by(
        owner_id=current_user.id).order_by(Scraper.name).all()]

# 使用絕對路徑，避免因工作目錄不同導致讀寫路徑對不上
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TEMPLATE_DIR = os.path.join(_PROJECT_ROOT, 'data', 'email_templates')
UPLOAD_DIR = os.path.join(_PROJECT_ROOT, 'data', 'uploads')


def _body_path(template_id):
    return os.path.join(TEMPLATE_DIR, f'{template_id}.html')


def _read_body(template):
    # 優先用 body_path，若不存在則 fallback 到標準路徑（相容舊資料）
    for path in [template.body_path, _body_path(template.id)]:
        if path and os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                return f.read()
    return ''


def _write_body(template_id, content):
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    with open(_body_path(template_id), 'w', encoding='utf-8') as f:
        f.write(content)


def _save_attachments(tmpl, files):
    base = os.path.join(UPLOAD_DIR, f'template_{tmpl.id}')
    os.makedirs(base, exist_ok=True)
    for f in files:
        if not f or not f.filename:
            continue
        stored_name = f'{uuid.uuid4().hex}_{f.filename}'
        path = os.path.join(base, stored_name)
        f.save(path)
        att = Attachment(
            template_id=tmpl.id,
            filename=f.filename,
            storage_path=path,
            file_size=os.path.getsize(path),
            mime_type=f.mimetype or 'application/octet-stream',
        )
        db.session.add(att)


@bp.route('/')
@login_required
def index():
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    import os as _os
    from jinja2 import Template as _JinjaTmpl

    page = request.args.get('page', 1, type=int)
    tag_filter = request.args.get('tag', '')
    query = EmailTemplate.query.filter_by(owner_id=current_user.id)
    if tag_filter:
        query = query.filter(EmailTemplate.tags.any(Tag.name == tag_filter))
    templates = query.order_by(EmailTemplate.created_at.desc()).paginate(page=page, per_page=20)
    all_tags = (Tag.query
                .filter_by(owner_id=current_user.id)
                .join(template_tags, Tag.id == template_tags.c.tag_id)
                .order_by(Tag.name).all())

    _local_tz = ZoneInfo(_os.environ.get('DISPLAY_TZ', 'Asia/Taipei'))
    today = _dt.now(_local_tz).strftime('%Y-%m-%d')
    rendered_subjects = {}
    for tmpl in templates.items:
        try:
            rendered_subjects[tmpl.id] = _JinjaTmpl(tmpl.subject).render(date=today)
        except Exception:
            rendered_subjects[tmpl.id] = tmpl.subject

    return render_template('templates_mgr/list.html', templates=templates,
                           rendered_subjects=rendered_subjects,
                           all_tags=all_tags, tag_filter=tag_filter)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TemplateForm()
    if form.validate_on_submit():
        tmpl = EmailTemplate(
            name=form.name.data,
            subject=form.subject.data,
            body_path='',
            variables=[],
            scraper_vars=json.loads(form.scraper_vars.data or '{}'),
            owner_id=current_user.id,
        )
        db.session.add(tmpl)
        db.session.flush()
        path = _body_path(tmpl.id)
        _write_body(tmpl.id, form.body.data)
        tmpl.body_path = path
        files = request.files.getlist('attachments')
        allowed = Config.ALLOWED_EXTENSIONS
        bad = [f.filename for f in files if f and f.filename and
               f.filename.rsplit('.', 1)[-1].lower() not in allowed]
        if bad:
            flash(f'不允許的檔案格式：{", ".join(bad)}', 'danger')
            return render_template('templates_mgr/create.html', form=form,
                                   scraper_choices=_scraper_choices())
        _save_attachments(tmpl, files)
        tmpl.tags = _parse_tags(form.tags.data or '', current_user.id)
        db.session.commit()
        flash('模板已建立', 'success')
        return redirect(url_for('templates_mgr.index'))
    return render_template('templates_mgr/create.html', form=form,
                           scraper_choices=_scraper_choices())


@bp.route('/<int:tmpl_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(tmpl_id):
    tmpl = db.session.get(EmailTemplate, tmpl_id)
    if tmpl is None or tmpl.owner_id != current_user.id:
        abort(404)

    form = TemplateForm(obj=tmpl)
    if request.method == 'GET':
        form.body.data = _read_body(tmpl)
        form.scraper_vars.data = json.dumps(tmpl.scraper_vars or {})
        form.tags.data = ', '.join(t.name for t in tmpl.tags)

    if form.validate_on_submit():
        tmpl.name = form.name.data
        tmpl.subject = form.subject.data
        tmpl.scraper_vars = json.loads(form.scraper_vars.data or '{}')
        _write_body(tmpl.id, form.body.data)
        tmpl.body_path = _body_path(tmpl.id)  # 同步確保 DB 路徑與實際檔案一致
        tmpl.tags = _parse_tags(form.tags.data or '', current_user.id)
        db.session.commit()
        flash('模板已更新', 'success')
        return redirect(url_for('templates_mgr.index'))

    return render_template('templates_mgr/edit.html', form=form, tmpl=tmpl,
                           scraper_choices=_scraper_choices())


@bp.route('/<int:tmpl_id>/delete', methods=['POST'])
@login_required
def delete(tmpl_id):
    tmpl = db.session.get(EmailTemplate, tmpl_id)
    if tmpl is None or tmpl.owner_id != current_user.id:
        abort(404)
    path = _body_path(tmpl.id)
    if os.path.exists(path):
        os.remove(path)
    upload_dir = os.path.join(UPLOAD_DIR, f'template_{tmpl.id}')
    if os.path.isdir(upload_dir):
        shutil.rmtree(upload_dir)
    db.session.delete(tmpl)
    db.session.commit()
    flash('模板已刪除', 'success')
    return redirect(url_for('templates_mgr.index'))


@bp.route('/<int:tmpl_id>/attachments/<int:att_id>/download')
@login_required
def download_attachment(tmpl_id, att_id):
    tmpl = db.session.get(EmailTemplate, tmpl_id)
    if tmpl is None or tmpl.owner_id != current_user.id:
        abort(404)
    att = db.session.get(Attachment, att_id)
    if att is None or att.template_id != tmpl_id:
        abort(404)
    return send_from_directory(
        os.path.dirname(att.storage_path),
        os.path.basename(att.storage_path),
        download_name=att.filename,
        as_attachment=False,
    )


@bp.route('/<int:tmpl_id>/attachments/upload', methods=['POST'])
@login_required
def upload_attachment(tmpl_id):
    tmpl = db.session.get(EmailTemplate, tmpl_id)
    if tmpl is None or tmpl.owner_id != current_user.id:
        return jsonify({'ok': False, 'error': '找不到模板'}), 404
    allowed = Config.ALLOWED_EXTENSIONS
    base = os.path.join(UPLOAD_DIR, f'template_{tmpl.id}')
    os.makedirs(base, exist_ok=True)
    saved = []
    for f in request.files.getlist('attachments'):
        if not f or not f.filename:
            continue
        ext = f.filename.rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
        if ext not in allowed:
            return jsonify({'ok': False, 'error': f'不允許的檔案格式：{f.filename}'}), 400
        stored_name = f'{uuid.uuid4().hex}_{f.filename}'
        path = os.path.join(base, stored_name)
        f.save(path)
        att = Attachment(
            template_id=tmpl.id,
            filename=f.filename,
            storage_path=path,
            file_size=os.path.getsize(path),
            mime_type=f.mimetype or 'application/octet-stream',
        )
        db.session.add(att)
        db.session.flush()
        saved.append({'id': att.id, 'filename': att.filename, 'file_size': att.file_size})
    db.session.commit()
    return jsonify({'ok': True, 'attachments': saved})


@bp.route('/<int:tmpl_id>/attachments/<int:att_id>/delete', methods=['POST'])
@login_required
def delete_attachment(tmpl_id, att_id):
    tmpl = db.session.get(EmailTemplate, tmpl_id)
    if tmpl is None or tmpl.owner_id != current_user.id:
        return jsonify({'ok': False, 'error': '找不到模板'}), 404
    att = db.session.get(Attachment, att_id)
    if att is None or att.template_id != tmpl_id:
        return jsonify({'ok': False, 'error': '找不到附件'}), 404
    if os.path.exists(att.storage_path):
        os.remove(att.storage_path)
    db.session.delete(att)
    db.session.commit()
    return jsonify({'ok': True})


@bp.route('/<int:tmpl_id>/preview')
@login_required
def preview(tmpl_id):
    tmpl = db.session.get(EmailTemplate, tmpl_id)
    if tmpl is None or tmpl.owner_id != current_user.id:
        abort(404)

    # Build preview context: scraper_vars use last_content as placeholder
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    import os as _os

    _local_tz = ZoneInfo(_os.environ.get('DISPLAY_TZ', 'Asia/Taipei'))
    preview_vars = {
        'date': _dt.now(_local_tz).strftime('%Y-%m-%d'),
    }
    scraper_warnings = []
    for var_name, scraper_id in (tmpl.scraper_vars or {}).items():
        scraper = db.session.get(Scraper, scraper_id)
        if scraper and scraper.last_content:
            preview_vars[var_name] = scraper.last_content
        else:
            preview_vars[var_name] = f'[{var_name}（尚無快取內容）]'
            scraper_warnings.append(var_name)

    # Render template body with Jinja2, same as mailer does
    from jinja2 import Environment, BaseLoader, Template as _JinjaTmpl, select_autoescape
    from markupsafe import Markup, escape as mk_escape

    def _nl2br(value):
        return Markup(mk_escape(value).replace('\n', Markup('<br>\n')))

    raw_body = _read_body(tmpl)
    try:
        env = Environment(loader=BaseLoader(), autoescape=select_autoescape(['html']))
        env.filters['nl2br'] = _nl2br
        rendered_body = env.from_string(raw_body).render(**preview_vars)
    except Exception as exc:
        rendered_body = raw_body
        scraper_warnings.append(f'模板渲染錯誤：{exc}')

    try:
        rendered_subject = _JinjaTmpl(tmpl.subject).render(**preview_vars)
    except Exception:
        rendered_subject = tmpl.subject

    attachments = Attachment.query.filter_by(template_id=tmpl_id).all()
    return render_template('templates_mgr/preview.html', tmpl=tmpl, body=rendered_body,
                           rendered_subject=rendered_subject,
                           attachments=attachments, scraper_warnings=scraper_warnings)
