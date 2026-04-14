import click

from app import db
from app.hosts import bp
from app.models import HostTemplate, HostTemplatePath


DEFAULT_TEMPLATES = [
    {
        'name': 'Web Server',
        'description': 'Nginx / Apache 常見設定檔路徑',
        'paths': [
            '/etc/nginx/nginx.conf',
            '/etc/nginx/conf.d/*.conf',
            '/etc/nginx/sites-enabled/*',
            '/etc/apache2/apache2.conf',
            '/etc/apache2/sites-enabled/*.conf',
        ],
    },
    {
        'name': 'DB Server',
        'description': 'MySQL / MariaDB / PostgreSQL 設定檔路徑',
        'paths': [
            '/etc/mysql/my.cnf',
            '/etc/mysql/mariadb.conf.d/*.cnf',
            '/etc/postgresql/*/main/postgresql.conf',
            '/etc/postgresql/*/main/pg_hba.conf',
        ],
    },
    {
        'name': 'General',
        'description': '通用 Linux 系統設定檔路徑',
        'paths': [
            '/etc/hosts',
            '/etc/hostname',
            '/etc/resolv.conf',
            '/etc/ssh/sshd_config',
            '/etc/crontab',
        ],
    },
]


@bp.cli.command('seed-templates')
def seed_templates():
    """建立預設主機類型模板（Web Server / DB Server / General）。已存在的模板會略過。"""
    created = 0
    for spec in DEFAULT_TEMPLATES:
        if HostTemplate.query.filter_by(name=spec['name']).first():
            click.echo(f'- skip: {spec["name"]}（已存在）')
            continue
        tpl = HostTemplate(name=spec['name'], description=spec['description'])
        for p in spec['paths']:
            tpl.template_paths.append(HostTemplatePath(path=p))
        db.session.add(tpl)
        created += 1
        click.echo(f'+ created: {spec["name"]}（{len(spec["paths"])} paths）')
    db.session.commit()
    click.echo(f'完成：新增 {created} 個模板')
