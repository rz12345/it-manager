"""網路設備模組測試：CRUD、分組可見性、廠商預設指令。"""
import pytest


@pytest.fixture()
def group(db):
    from app.models import Group
    g = Group(name='core-net')
    db.session.add(g)
    db.session.commit()
    return g


@pytest.fixture()
def device(db, group):
    from app.crypto import encrypt
    from app.models import Device
    d = Device(name='sw-01', ip_address='10.1.1.1', port=22,
              vendor='cisco_ios', username='admin',
              password_enc=encrypt('devpass'),
              group_id=group.id)
    db.session.add(d)
    db.session.commit()
    return d


def _form_data(**overrides):
    data = {
        'name': 'sw-01',
        'ip_address': '10.1.1.1',
        'port': '22',
        'vendor': 'cisco_ios',
        'username': 'admin',
        'password': 'devpass',
        'enable_password': '',
        'backup_command': '',
        'description': '',
        'group_id': '0',
        'is_active': 'y',
    }
    data.update(overrides)
    return data


def test_admin_create_device(client, logged_in_admin, db):
    resp = client.post('/it-manager/devices/create',
                       data=_form_data(), follow_redirects=False)
    assert resp.status_code == 302

    from app.models import Device
    d = Device.query.filter_by(name='sw-01').first()
    assert d is not None
    assert d.vendor == 'cisco_ios'
    # 未自訂指令 → effective_command 應為廠商預設
    assert d.effective_command == 'show running-config'


def test_custom_backup_command(client, logged_in_admin, db):
    resp = client.post('/it-manager/devices/create',
                       data=_form_data(name='fw-01', vendor='paloalto_panos',
                                       backup_command='show config running | no-more'),
                       follow_redirects=False)
    assert resp.status_code == 302
    from app.models import Device
    d = Device.query.filter_by(name='fw-01').first()
    assert d.effective_command == 'show config running | no-more'


def test_device_visibility(client, db, regular_user, group, device, login):
    login('bob', 'bob-pass-12345')
    resp = client.get(f'/it-manager/devices/{device.id}')
    assert resp.status_code == 403

    regular_user.groups.append(group)
    db.session.commit()
    resp = client.get(f'/it-manager/devices/{device.id}')
    assert resp.status_code == 200


def test_regular_user_cannot_delete(client, logged_in_user, device):
    resp = client.post(f'/it-manager/devices/{device.id}/delete')
    assert resp.status_code == 403


def test_admin_delete_device(client, logged_in_admin, device):
    resp = client.post(f'/it-manager/devices/{device.id}/delete',
                       follow_redirects=False)
    assert resp.status_code == 302
    from app.models import Device
    assert Device.query.get(device.id) is None
