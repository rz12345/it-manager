"""Pytest fixtures — 測試用 Flask app、DB、使用者登入 helper。"""
from __future__ import annotations

import os
import tempfile

import pytest
from cryptography.fernet import Fernet


class TestConfig:
    TESTING = True
    WTF_CSRF_ENABLED = False
    SECRET_KEY = 'test-secret'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    CRYPTO_KEY = Fernet.generate_key().decode()
    DISPLAY_TZ = 'Asia/Taipei'
    APPLICATION_ROOT = '/config-manager'


@pytest.fixture()
def app():
    # 每個測試使用獨立暫存目錄（DB 與備份檔案）
    tmpdir = tempfile.mkdtemp(prefix='cm-test-')
    db_path = os.path.join(tmpdir, 'test.db')
    TestConfig.SQLALCHEMY_DATABASE_URI = f'sqlite:///{db_path}'
    TestConfig.BACKUP_BASE_PATH = tmpdir

    from app import create_app, db as _db
    _app = create_app(TestConfig)

    with _app.app_context():
        _db.create_all()
        yield _app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def db(app):
    from app import db as _db
    return _db


@pytest.fixture()
def client(app):
    return app.test_client()


# ── 使用者 helpers ──
@pytest.fixture()
def admin_user(db):
    from app.models import User
    u = User(username='admin', email='admin@example.com', is_admin=True)
    u.set_password('admin-pass-12345')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def regular_user(db):
    from app.models import User
    u = User(username='bob', email='bob@example.com', is_admin=False)
    u.set_password('bob-pass-12345')
    db.session.add(u)
    db.session.commit()
    return u


@pytest.fixture()
def login(client):
    def _login(username: str, password: str):
        return client.post('/config-manager/auth/login',
                           data={'username': username, 'password': password},
                           follow_redirects=False)
    return _login


@pytest.fixture()
def logged_in_admin(client, admin_user, login):
    login('admin', 'admin-pass-12345')
    return admin_user


@pytest.fixture()
def logged_in_user(client, regular_user, login):
    login('bob', 'bob-pass-12345')
    return regular_user
