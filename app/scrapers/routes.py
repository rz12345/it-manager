from datetime import datetime

from flask import abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app import db
from app.models import Group, Scraper, ScraperLog, Tag, _tag_color, scraper_tags
from app.scrapers import bp
from app.scrapers.forms import ScraperForm


def _user_can_access_scraper(scraper) -> bool:
    if scraper is None:
        return False
    if current_user.is_admin:
        return True
    if scraper.owner_id == current_user.id:
        return True
    return scraper.group_id is not None and scraper.group_id in (current_user.group_ids or [])


def _visible_scrapers_query():
    q = Scraper.query
    if current_user.is_admin:
        return q
    gids = current_user.group_ids or []
    if gids:
        return q.filter(db.or_(Scraper.owner_id == current_user.id,
                               Scraper.group_id.in_(gids)))
    return q.filter(Scraper.owner_id == current_user.id)


def _populate_group_choices(form):
    if current_user.is_admin:
        groups = Group.query.order_by(Group.name).all()
    else:
        gids = current_user.group_ids or []
        groups = Group.query.filter(Group.id.in_(gids)).order_by(Group.name).all() if gids else []
    form.group_id.choices = [(0, '— 無（僅擁有者可見）—')] + [(g.id, g.name) for g in groups]


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


@bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    tag_filter = request.args.get('tag', '')
    query = _visible_scrapers_query()
    if tag_filter:
        query = query.filter(Scraper.tags.any(Tag.name == tag_filter))
    scrapers = query.order_by(Scraper.created_at.desc()).paginate(page=page, per_page=20)
    all_tags = (Tag.query
                .filter_by(owner_id=current_user.id)
                .join(scraper_tags, Tag.id == scraper_tags.c.tag_id)
                .order_by(Tag.name).all())
    return render_template('scrapers/list.html', scrapers=scrapers,
                           all_tags=all_tags, tag_filter=tag_filter)


@bp.route('/create', methods=['GET', 'POST'])
@login_required
def create():
    form = ScraperForm()
    _populate_group_choices(form)
    if form.validate_on_submit():
        scraper = Scraper(
            name=form.name.data,
            url=form.url.data,
            owner_id=current_user.id,
            group_id=form.group_id.data or None,
            extract_type=form.extract_type.data,
            extract_pattern=form.extract_pattern.data,
        )
        db.session.add(scraper)
        db.session.flush()
        scraper.tags = _parse_tags(form.tags.data or '', current_user.id)
        db.session.commit()
        flash('爬蟲已建立', 'success')
        return redirect(url_for('scrapers.index'))
    return render_template('scrapers/create.html', form=form)


@bp.route('/<int:scraper_id>')
@login_required
def detail(scraper_id):
    scraper = db.session.get(Scraper, scraper_id)
    if not _user_can_access_scraper(scraper):
        abort(404)
    return render_template('scrapers/detail.html', scraper=scraper)


@bp.route('/<int:scraper_id>/edit', methods=['GET', 'POST'])
@login_required
def edit(scraper_id):
    scraper = db.session.get(Scraper, scraper_id)
    if not _user_can_access_scraper(scraper):
        abort(404)

    form = ScraperForm(obj=scraper)
    _populate_group_choices(form)
    if request.method == 'GET':
        form.tags.data = ', '.join(t.name for t in scraper.tags)
        form.group_id.data = scraper.group_id or 0
    if form.validate_on_submit():
        scraper.name = form.name.data
        scraper.url = form.url.data
        scraper.group_id = form.group_id.data or None
        scraper.extract_type = form.extract_type.data
        scraper.extract_pattern = form.extract_pattern.data
        scraper.tags = _parse_tags(form.tags.data or '', current_user.id)
        db.session.commit()
        flash('爬蟲已更新', 'success')
        return redirect(url_for('scrapers.index'))
    return render_template('scrapers/edit.html', form=form, scraper=scraper)


@bp.route('/<int:scraper_id>/delete', methods=['POST'])
@login_required
def delete(scraper_id):
    scraper = db.session.get(Scraper, scraper_id)
    if not _user_can_access_scraper(scraper):
        abort(404)
    db.session.delete(scraper)
    db.session.commit()
    flash('爬蟲已刪除', 'success')
    return redirect(url_for('scrapers.index'))


@bp.route('/<int:scraper_id>/test', methods=['POST'])
@login_required
def test(scraper_id):
    scraper = db.session.get(Scraper, scraper_id)
    if not _user_can_access_scraper(scraper):
        abort(404)

    from scheduler.scraper import scrape_and_extract

    now = datetime.utcnow()
    log = ScraperLog(scraper_id=scraper.id, checked_at=now)

    try:
        content, _ = scrape_and_extract(
            scraper.url, scraper.extract_type, scraper.extract_pattern
        )
        log.status = 'success'
        log.content = content
        scraper.last_content = content
        scraper.last_checked = now
        flash(f'測試成功，擷取內容（前 200 字）：{content[:200]}', 'success')
    except Exception as exc:
        log.status = 'error'
        log.error_message = str(exc)
        scraper.last_checked = now
        flash(f'測試失敗：{exc}', 'danger')

    db.session.add(log)
    db.session.commit()
    return redirect(url_for('scrapers.detail', scraper_id=scraper.id))
