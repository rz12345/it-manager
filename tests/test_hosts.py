"""Linux 主機模組測試：CRUD、分組可見性、備份路徑管理。"""
import pytest


@pytest.fixture()
def group(db):
    from app.models import Group
    g = Group(name='web', description='Web Servers')
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture()
def host(db, group):
    from app.crypto import encrypt
    from app.models import Host
    h = Host(name='web-01', ip_address='10.0.0.1', port=22,
            username='root', password_enc=encrypt('secret'),
            group_id=group.id)
    db.session.add(h)
    db.session.commit()
    return h


def _form_data(**overrides):
    data = {
        'name': 'web-01',
        'ip_address': '10.0.0.1',
        'port': '22',
        'username': 'root',
        'password': 'secret',
        'description': '',
        'group_id': '0',
        'template_id': '0',
        'is_active': 'y',
    }
    data.update(overrides)
    return data


def test_index_requires_login(client, admin_user):
    resp = client.get('/it-manager/assets/', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.location


def test_admin_can_create_host(client, logged_in_admin, db):
    resp = client.post('/it-manager/hosts/create',
                       data=_form_data(), follow_redirects=False)
    assert resp.status_code == 302

    from app.models import Host
    h = Host.query.filter_by(name='web-01').first()
    assert h is not None
    assert h.ip_address == '10.0.0.1'
    assert h.password_enc != 'secret'  # 應加密
    from app.crypto import decrypt
    assert decrypt(h.password_enc) == 'secret'


def test_regular_user_cannot_create_host(client, logged_in_user):
    resp = client.post('/it-manager/hosts/create',
                       data=_form_data(), follow_redirects=False)
    assert resp.status_code == 403


def test_host_visibility_respects_group(client, db, regular_user, group, host, login):
    """一般使用者僅能看到自己所屬分組的主機。"""
    # 未加入分組前不可見（detail → 403）
    login('bob', 'bob-pass-12345')
    resp = client.get(f'/it-manager/hosts/{host.id}', follow_redirects=False)
    assert resp.status_code == 403

    # 加入分組後可見
    regular_user.groups.append(group)
    db.session.commit()
    resp = client.get(f'/it-manager/hosts/{host.id}', follow_redirects=False)
    assert resp.status_code == 200


def test_admin_edit_host_keeps_password_when_blank(client, logged_in_admin, host, db):
    """編輯時密碼留白應保留原值。"""
    original_pw = host.password_enc
    resp = client.post(f'/it-manager/hosts/{host.id}/edit',
                       data=_form_data(name='web-01-renamed', password=''),
                       follow_redirects=False)
    assert resp.status_code == 302
    db.session.refresh(host)
    assert host.name == 'web-01-renamed'
    assert host.password_enc == original_pw


def test_admin_delete_host(client, logged_in_admin, host, db):
    resp = client.post(f'/it-manager/hosts/{host.id}/delete',
                       follow_redirects=False)
    assert resp.status_code == 302
    from app.models import Host
    assert Host.query.get(host.id) is None


def test_add_file_path(client, logged_in_admin, host, db):
    resp = client.post(f'/it-manager/hosts/{host.id}/paths/add',
                       data={'path': '/etc/nginx/nginx.conf'},
                       follow_redirects=False)
    assert resp.status_code == 302
    db.session.refresh(host)
    assert len(host.file_paths) == 1
    assert host.file_paths[0].path == '/etc/nginx/nginx.conf'
    assert host.file_paths[0].source == 'manual'


def test_add_file_path_rejects_relative(client, logged_in_admin, host):
    resp = client.post(f'/it-manager/hosts/{host.id}/paths/add',
                       data={'path': 'etc/no-slash'},
                       follow_redirects=True)
    # 失敗會 flash 並 redirect；flash 訊息中含絕對路徑提示
    assert resp.status_code == 200
    assert b'/ ' in resp.data or '絕對'.encode('utf-8') in resp.data


def test_template_applies_paths(client, logged_in_admin, db):
    from app.models import HostTemplate, HostTemplatePath
    t = HostTemplate(name='Web Server')
    t.template_paths.append(HostTemplatePath(path='/etc/nginx/nginx.conf'))
    t.template_paths.append(HostTemplatePath(path='/etc/hosts'))
    db.session.add(t)
    db.session.commit()

    resp = client.post('/it-manager/hosts/create',
                       data=_form_data(name='web-10', template_id=str(t.id)),
                       follow_redirects=False)
    assert resp.status_code == 302

    from app.models import Host
    h = Host.query.filter_by(name='web-10').first()
    paths = {fp.path: fp.source for fp in h.file_paths}
    assert paths == {'/etc/nginx/nginx.conf': 'template', '/etc/hosts': 'template'}
