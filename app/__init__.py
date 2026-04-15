import os
from datetime import timezone
from zoneinfo import ZoneInfo

from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_wtf.csrf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix

db = SQLAlchemy()
login_manager = LoginManager()
migrate = Migrate()
csrf = CSRFProtect()

_URL_PREFIX = '/it-manager'


def create_app(config=None):
    app = Flask(__name__, static_url_path=f'{_URL_PREFIX}/static')

    from app.config import Config
    app.config.from_object(Config)
    if config:
        app.config.from_object(config)

    # Handle X-Forwarded-* headers from nginx reverse proxy
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    # Ensure data and backup directories exist
    import re
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    m = re.match(r'sqlite:///(.+)', db_uri)
    if m:
        os.makedirs(os.path.dirname(m.group(1)), exist_ok=True)

    backup_base = app.config.get('BACKUP_BASE_PATH', '')
    if backup_base:
        os.makedirs(os.path.join(backup_base, 'hosts'), exist_ok=True)
        os.makedirs(os.path.join(backup_base, 'devices'), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'warning'

    # Import models so SQLAlchemy / Alembic can discover them
    from app import models  # noqa: F401

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix=f'{_URL_PREFIX}/auth')

    from app.dashboard import bp as dashboard_bp
    app.register_blueprint(dashboard_bp, url_prefix=f'{_URL_PREFIX}/dashboard')

    from app.assets import bp as assets_bp
    app.register_blueprint(assets_bp, url_prefix=f'{_URL_PREFIX}/assets')

    from app.hosts import bp as hosts_bp
    app.register_blueprint(hosts_bp, url_prefix=f'{_URL_PREFIX}/hosts')

    from app.devices import bp as devices_bp
    app.register_blueprint(devices_bp, url_prefix=f'{_URL_PREFIX}/devices')

    from app.groups import bp as groups_bp
    app.register_blueprint(groups_bp, url_prefix=f'{_URL_PREFIX}/groups')

    from app.backups import bp as backups_bp
    app.register_blueprint(backups_bp, url_prefix=f'{_URL_PREFIX}/backups')

    from app.tasks import bp as tasks_bp
    app.register_blueprint(tasks_bp, url_prefix=f'{_URL_PREFIX}/tasks')

    from app.email_tasks import bp as email_tasks_bp
    app.register_blueprint(email_tasks_bp, url_prefix=f'{_URL_PREFIX}/email-tasks')

    from app.compare import bp as compare_bp
    app.register_blueprint(compare_bp, url_prefix=f'{_URL_PREFIX}/compare')

    from app.settings import bp as settings_bp
    app.register_blueprint(settings_bp, url_prefix=f'{_URL_PREFIX}/settings')

    from app.credentials import bp as credentials_bp
    app.register_blueprint(credentials_bp, url_prefix=f'{_URL_PREFIX}/credentials')

    from app.logs import bp as logs_bp
    app.register_blueprint(logs_bp, url_prefix=f'{_URL_PREFIX}/logs')

    from app.templates_mgr import bp as templates_mgr_bp
    app.register_blueprint(templates_mgr_bp, url_prefix=f'{_URL_PREFIX}/templates')

    from app.scrapers import bp as scrapers_bp
    app.register_blueprint(scrapers_bp, url_prefix=f'{_URL_PREFIX}/scrapers')

    @app.before_request
    def redirect_to_setup():
        from flask import request as req
        from sqlalchemy.exc import OperationalError
        try:
            from app.models import User
        except ImportError:
            return
        if req.endpoint in ('auth.setup', 'auth.login', 'static'):
            return
        try:
            if User.query.count() == 0:
                return redirect(url_for('auth.setup'))
        except OperationalError:
            return redirect(url_for('auth.setup'))

    @app.route('/')
    @app.route(f'{_URL_PREFIX}/')
    def index():
        return redirect(url_for('dashboard.index'))

    @app.context_processor
    def inject_alert_count():
        from flask_login import current_user
        from sqlalchemy.exc import SQLAlchemyError
        if not getattr(current_user, 'is_authenticated', False):
            return {'unread_alert_count': 0}
        try:
            from app.models import BackupAlert
            return {'unread_alert_count': BackupAlert.query.filter_by(is_read=False).count()}
        except SQLAlchemyError:
            return {'unread_alert_count': 0}

    _tz = ZoneInfo(app.config.get('DISPLAY_TZ', 'Asia/Taipei'))

    @app.template_filter('localtime')
    def localtime_filter(dt, fmt='%Y-%m-%d %H:%M'):
        if dt is None:
            return '—'
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_tz).strftime(fmt)

    return app
