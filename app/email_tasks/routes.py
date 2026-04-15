import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from croniter import croniter
from flask import abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import EmailRun, EmailTask, EmailTemplate, Group, Tag, Task, TaskTemplate, _tag_color, task_tags
from app.email_tasks import bp
from app.email_tasks.forms import TaskForm


def _user_can_access_task(task) -> bool:
    if task is None:
        return False
    if current_user.is_admin:
        return True
    if task.owner_id == current_user.id:
        return True
    return task.group_id is not None and task.group_id in (current_user.group_ids or [])


def _visible_tasks_query():
    q = EmailTask.query
    if current_user.is_admin:
        return q
    gids = current_user.group_ids or []
    if gids:
        return q.filter(db.or_(EmailTask.owner_id == current_user.id,
                               EmailTask.group_id.in_(gids)))
    return q.filter(EmailTask.owner_id == current_user.id)


def _populate_group_choices(form):
    if current_user.is_admin:
        groups = Group.query.order_by(Group.name).all()
    else:
        gids = current_user.group_ids or []
        groups = Group.query.filter(Group.id.in_(gids)).order_by(Group.name).all() if gids else []
    form.group_id.choices = [(0, '— 無（僅擁有者可見）—')] + [(g.id, g.name) for g in groups]


_LOCAL_TZ = ZoneInfo(os.environ.get('DISPLAY_TZ', 'Asia/Taipei'))


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


def _basic_to_cron(frequency, time_str, day=None, week=None):
    hh, mm = time_str.strip().split(':')
    if frequency == 'daily':
        return f'{int(mm)} {int(hh)} * * *'
    if frequency == 'monthly':
        suffix = 'L' if week == 'L' else f'#{week}'
        return f'{int(mm)} {int(hh)} * * {day}{suffix}'
    return f'{int(mm)} {int(hh)} * * {day}'


def _compute_next_run(task):
    if task.schedule_mode != 'once':
        now_local = datetime.now(_LOCAL_TZ)
        it = croniter(task.cron_expr, now_local)
        next_local = it.get_next(datetime)
        return next_local.astimezone(timezone.utc).replace(tzinfo=None)
    return task.scheduled_at


def _template_choices():
    return [(t.id, t.name) for t in EmailTemplate.query.filter_by(
        owner_id=current_user.id).order_by(EmailTemplate.name).all()]


def _save_task_templates(task, template_ids):
    for tt in list(task.task_templates):
        db.session.delete(tt)
    db.session.flush()
    for order, tid in enumerate(template_ids):
        db.session.add(TaskTemplate(task_id=task.id, template_id=tid, order=order))


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    tag_filter = request.args.get('tag', '')
    query = _visible_tasks_query()
    if tag_filter:
        query = query.filter(EmailTask.tags.any(Tag.name == tag_filter))
    tasks = query.order_by(EmailTask.created_at.desc()).paginate(page=page, per_page=20)
    all_tags = (Tag.query
                .filter_by(owner_id=current_user.id)
                .join(task_tags, Tag.id == task_tags.c.tag_id)
                .order_by(Tag.name).all())
    week_ago = datetime.utcnow() - timedelta(days=7)
    visible_ids_subq = _visible_tasks_query().with_entities(EmailTask.id).subquery()
    summary = {
        'active': _visible_tasks_query().filter(EmailTask.is_active.is_(True)).count(),
        'sent_week': EmailRun.query.filter(
            EmailRun.task_id.in_(db.session.query(visible_ids_subq)),
            EmailRun.started_at >= week_ago,
        ).count(),
        'failed_week': EmailRun.query.filter(
            EmailRun.task_id.in_(db.session.query(visible_ids_subq)),
            EmailRun.status == 'failed',
            EmailRun.started_at >= week_ago,
        ).count(),
    }
    return render_template('email_tasks/list.html', tasks=tasks, summary=summary,
                           all_tags=all_tags, tag_filter=tag_filter)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = TaskForm()
    form.template_ids.choices = _template_choices()
    _populate_group_choices(form)
    if form.validate_on_submit():
        mode = form.schedule_mode.data
        if mode == 'basic':
            freq = form.basic_frequency.data
            needs_day = freq in ('weekly', 'monthly')
            cron_expr = _basic_to_cron(
                freq,
                form.basic_time.data,
                form.basic_day.data if needs_day else None,
                form.basic_week.data if freq == 'monthly' else None,
            )
            scheduled_at = None
            basic_params = {
                'frequency': freq,
                'time': form.basic_time.data.strip(),
                'day': form.basic_day.data,
                'week': form.basic_week.data,
            }
        elif mode == 'advanced':
            cron_expr = form.cron_expr.data.strip()
            scheduled_at = None
            basic_params = None
        else:  # once
            cron_expr = None
            local_dt = form.scheduled_at.data
            scheduled_at = (local_dt.replace(tzinfo=_LOCAL_TZ)
                            .astimezone(timezone.utc)
                            .replace(tzinfo=None))
            basic_params = None

        task = EmailTask(
            name=form.name.data,
            description=form.description.data,
            owner_id=current_user.id,
            group_id=form.group_id.data or None,
            recipients=form.recipients.data,
            schedule_mode=mode,
            schedule_basic_params=basic_params,
            cron_expr=cron_expr,
            scheduled_at=scheduled_at,
        )
        db.session.add(task)
        db.session.flush()
        _save_task_templates(task, form.template_ids.data)
        task.tags = _parse_tags(form.tags.data or '', current_user.id)
        task.next_run = _compute_next_run(task)
        db.session.commit()
        flash('任務已建立', 'success')
        return redirect(url_for('email_tasks.index'))
    return render_template('email_tasks/create.html', form=form)


@bp.route('/<int:task_id>')
@login_required
def detail(task_id):
    task = db.session.get(EmailTask, task_id)
    if not _user_can_access_task(task):
        abort(404)
    return render_template('email_tasks/detail.html', task=task)


@bp.route('/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(task_id):
    task = db.session.get(EmailTask, task_id)
    if not _user_can_access_task(task):
        abort(404)

    form = TaskForm(obj=task)
    form.template_ids.choices = _template_choices()
    _populate_group_choices(form)

    if form.validate_on_submit():
        mode = form.schedule_mode.data
        if mode == 'basic':
            freq = form.basic_frequency.data
            needs_day = freq in ('weekly', 'monthly')
            cron_expr = _basic_to_cron(
                freq,
                form.basic_time.data,
                form.basic_day.data if needs_day else None,
                form.basic_week.data if freq == 'monthly' else None,
            )
            scheduled_at = None
            basic_params = {
                'frequency': freq,
                'time': form.basic_time.data.strip(),
                'day': form.basic_day.data,
                'week': form.basic_week.data,
            }
        elif mode == 'advanced':
            cron_expr = form.cron_expr.data.strip()
            scheduled_at = None
            basic_params = None
        else:
            cron_expr = None
            local_dt = form.scheduled_at.data
            scheduled_at = (local_dt.replace(tzinfo=_LOCAL_TZ)
                            .astimezone(timezone.utc)
                            .replace(tzinfo=None))
            basic_params = None

        task.name = form.name.data
        task.description = form.description.data
        task.group_id = form.group_id.data or None
        task.recipients = form.recipients.data
        task.schedule_mode = mode
        task.schedule_basic_params = basic_params
        task.cron_expr = cron_expr
        task.scheduled_at = scheduled_at
        task.next_run = _compute_next_run(task)
        _save_task_templates(task, form.template_ids.data)
        task.tags = _parse_tags(form.tags.data or '', current_user.id)
        db.session.commit()
        flash('任務已更新', 'success')
        return redirect(url_for('email_tasks.index'))

    if request.method == 'GET':
        form.tags.data = ', '.join(t.name for t in task.tags)
        form.template_ids.data = [tt.template_id for tt in task.task_templates]
        form.group_id.data = task.group_id or 0
        form.schedule_mode.data = task.schedule_mode or 'advanced'
        if task.scheduled_at:
            utc_dt = task.scheduled_at.replace(tzinfo=timezone.utc)
            form.scheduled_at.data = utc_dt.astimezone(_LOCAL_TZ).replace(tzinfo=None)
        if task.schedule_basic_params:
            bp_data = task.schedule_basic_params
            form.basic_frequency.data = bp_data.get('frequency', 'daily')
            form.basic_time.data = bp_data.get('time', '')
            form.basic_day.data = bp_data.get('day', 1)
            form.basic_week.data = bp_data.get('week', '1')
    return render_template('email_tasks/edit.html', form=form, task=task)


@bp.route('/<int:task_id>/delete', methods=['POST'])
@login_required
def delete(task_id):
    task = db.session.get(EmailTask, task_id)
    if not _user_can_access_task(task):
        abort(404)
    db.session.delete(task)
    db.session.commit()
    flash('任務已刪除', 'success')
    return redirect(url_for('email_tasks.index'))


@bp.route('/<int:task_id>/test-send', methods=['POST'])
@login_required
def test_send(task_id):
    task = db.session.get(EmailTask, task_id)
    if not _user_can_access_task(task):
        abort(404)

    from app.settings_store import get_setting, get_smtp_cfg
    test_email = (get_setting('TEST_EMAIL') or '').strip()
    if not test_email:
        return jsonify({'ok': False, 'error': '尚未設定測試收件人，請至系統設定頁面填寫 TEST_EMAIL。'}), 400

    if not task.task_templates:
        return jsonify({'ok': False, 'error': '此任務尚未設定郵件模板。'}), 400

    smtp_cfg = get_smtp_cfg()

    from scheduler.mailer import send_email
    from scheduler.email_task import _fetch_scraper_vars
    errors = []
    for tt in task.task_templates:
        tmpl = tt.template
        scraper_content, _ = _fetch_scraper_vars(tmpl)
        merged_vars = {**(task.template_vars or {}), **scraper_content}
        attachments = [
            {'filename': a.filename, 'storage_path': a.storage_path}
            for a in tmpl.attachments
        ]
        task_dict = {
            'recipients': test_email,
            'subject':    tmpl.subject,
            'template_vars': merged_vars,
        }
        try:
            send_email(task_dict, tmpl.body_path, attachments, smtp_cfg)
        except Exception as exc:
            errors.append(f'[{tmpl.name}] {exc}')

    db.session.commit()

    if errors:
        return jsonify({'ok': False, 'error': '部分模板寄送失敗：\n' + '\n'.join(errors)}), 500

    return jsonify({'ok': True, 'message': f'測試信已寄送至 {test_email}'})


@bp.route('/<int:task_id>/toggle', methods=['POST'])
@login_required
def toggle(task_id):
    task = db.session.get(EmailTask, task_id)
    if not _user_can_access_task(task):
        abort(404)
    task.is_active = not task.is_active
    db.session.commit()
    state = '啟用' if task.is_active else '暫停'
    flash(f'任務已{state}', 'success')
    return redirect(url_for('email_tasks.index'))
