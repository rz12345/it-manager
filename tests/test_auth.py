"""驗證模組測試：初始 setup、登入、登出。"""


def test_first_visit_redirects_to_setup(client):
    """無任何使用者時，/login 應導向 /setup。"""
    resp = client.get('/it-manager/auth/login', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/setup' in resp.location


def test_setup_creates_admin_and_logs_in(client, db):
    from app.models import User
    resp = client.post('/it-manager/auth/setup', data={
        'username': 'owner',
        'email': 'owner@example.com',
        'password': 'owner-secret-1',
        'password_confirm': 'owner-secret-1',
    }, follow_redirects=False)
    assert resp.status_code == 302
    assert '/dashboard' in resp.location

    u = User.query.filter_by(username='owner').first()
    assert u is not None and u.is_admin


def test_setup_rejects_when_user_exists(client, admin_user):
    """已有使用者時 /setup 應重導 /login。"""
    resp = client.get('/it-manager/auth/setup', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.location


def test_login_success(client, admin_user, login):
    resp = login('admin', 'admin-pass-12345')
    assert resp.status_code == 302
    assert '/dashboard' in resp.location


def test_login_failure_flashes(client, admin_user, login):
    resp = login('admin', 'wrong-password')
    # 失敗會重新渲染登入頁（200），而非重導
    assert resp.status_code == 200

    from app.models import LoginLog
    assert LoginLog.query.filter_by(status='failed').count() == 1


def test_logout(client, logged_in_admin):
    resp = client.get('/it-manager/auth/logout', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.location

    from app.models import LoginLog
    assert LoginLog.query.filter_by(action='logout', status='success').count() == 1
