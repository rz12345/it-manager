from flask import flash, redirect, render_template, request, url_for
from app import db
from app.groups import bp
from app.groups.decorators import admin_required
from app.groups.forms import GroupForm
from app.models import Device, Group, Host, User


def _load_user_choices(form: GroupForm):
    users = User.query.order_by(User.username).all()
    form.members.choices = [
        (u.id, f'{u.username}{" (Admin)" if u.is_admin else ""}')
        for u in users
    ]


@bp.route('/')
@admin_required
def index():
    return redirect(url_for('settings.index', tab='groups'))


@bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create():
    form = GroupForm()
    _load_user_choices(form)

    if form.validate_on_submit():
        name = form.name.data.strip()
        if Group.query.filter_by(name=name).first():
            flash('分組名稱已存在', 'danger')
        else:
            group = Group(name=name, description=(form.description.data or '').strip())
            if form.members.data:
                group.users = User.query.filter(User.id.in_(form.members.data)).all()
            db.session.add(group)
            db.session.commit()
            flash(f'已建立分組「{group.name}」', 'success')
            return redirect(url_for('settings.index', tab='groups'))

    return render_template('groups/form.html', form=form, mode='create', group=None)


@bp.route('/<int:group_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit(group_id):
    group = Group.query.get_or_404(group_id)
    form = GroupForm(obj=group)
    _load_user_choices(form)

    if request.method == 'GET':
        form.members.data = [u.id for u in group.users]

    if form.validate_on_submit():
        name = form.name.data.strip()
        dup = Group.query.filter(Group.name == name, Group.id != group.id).first()
        if dup:
            flash('分組名稱已存在', 'danger')
        else:
            group.name = name
            group.description = (form.description.data or '').strip()
            group.users = User.query.filter(User.id.in_(form.members.data or [])).all()
            db.session.commit()
            flash(f'已更新分組「{group.name}」', 'success')
            return redirect(url_for('settings.index', tab='groups'))

    return render_template('groups/form.html', form=form, mode='edit', group=group)


@bp.route('/<int:group_id>/delete', methods=['POST'])
@admin_required
def delete(group_id):
    group = Group.query.get_or_404(group_id)
    host_cnt = Host.query.filter_by(group_id=group.id).count()
    device_cnt = Device.query.filter_by(group_id=group.id).count()
    if host_cnt or device_cnt:
        flash(
            f'無法刪除：分組仍關聯 {host_cnt} 台主機、{device_cnt} 台設備，'
            '請先將其移出此分組。', 'danger'
        )
        return redirect(url_for('settings.index', tab='groups'))

    name = group.name
    db.session.delete(group)
    db.session.commit()
    flash(f'已刪除分組「{name}」', 'info')
    return redirect(url_for('settings.index', tab='groups'))
