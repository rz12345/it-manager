"""備份模組測試：列表可見性、排程設定、下載、刪除。"""
import os
from datetime import datetime, timezone

import pytest


@pytest.fixture()
def host_with_run(db, tmp_path):
    from app.crypto import encrypt
    from app.models import BackupRecord, BackupRun, Host

    h = Host(name='h1', ip_address='1.1.1.1', port=22,
            username='u', password_enc=encrypt('p'))
    db.session.add(h)
    db.session.commit()

    # 建立一次成功備份 + 一個實體檔案
    storage = tmp_path / 'sample.conf'
    storage.write_bytes(b'hello\n')

    run = BackupRun(target_type='host', host_id=h.id,
                    status='success', triggered_by='manual',
                    started_at=datetime.now(timezone.utc),
                    finished_at=datetime.now(timezone.utc),
                    file_count=1)
    db.session.add(run)
    db.session.flush()
    rec = BackupRecord(run_id=run.id, file_path='/etc/hello',
                       storage_path=str(storage),
                       file_size=6, checksum='abc',
                       status='success')
    db.session.add(rec)
    db.session.commit()
    return h, run, rec


def test_backup_index_requires_login(client):
    resp = client.get('/it-manager/backups/', follow_redirects=False)
    assert resp.status_code == 302


def test_admin_sees_all_runs(client, logged_in_admin, host_with_run):
    resp = client.get('/it-manager/backups/')
    assert resp.status_code == 200
    assert b'h1' in resp.data


def test_regular_user_visibility_filtered(client, db, regular_user, host_with_run, login):
    """一般使用者無分組時備份歷史列表不應看到任何資料。"""
    login('bob', 'bob-pass-12345')
    resp = client.get('/it-manager/backups/')
    assert resp.status_code == 200
    # 列表應顯示「無」提示而不出現 h1
    assert b'h1' not in resp.data


def test_download_record_admin(client, logged_in_admin, host_with_run):
    _, _, rec = host_with_run
    resp = client.get(f'/it-manager/backups/record/{rec.id}/download')
    assert resp.status_code == 200
    assert resp.data == b'hello\n'


def test_download_record_denied_for_outside_group(client, logged_in_user, host_with_run):
    _, _, rec = host_with_run
    resp = client.get(f'/it-manager/backups/record/{rec.id}/download')
    assert resp.status_code == 403


def test_admin_delete_run_removes_storage(client, logged_in_admin, host_with_run, db):
    _, run, rec = host_with_run
    storage_path = rec.storage_path
    assert os.path.exists(storage_path)

    resp = client.post(f'/it-manager/backups/run/{run.id}/delete',
                       follow_redirects=False)
    assert resp.status_code == 302
    assert not os.path.exists(storage_path)

    from app.models import BackupRun, BackupRecord
    assert BackupRun.query.get(run.id) is None
    assert BackupRecord.query.get(rec.id) is None  # cascade


def test_task_create_and_run_now(client, logged_in_admin, host_with_run, monkeypatch):
    """建立 BackupTask、手動執行 — scheduler 缺失時回 501 訊息。"""
    import sys
    h, _, _ = host_with_run
    resp = client.post('/it-manager/tasks/create',
                       data={'name': 't1',
                             'schedule_mode': 'advanced',
                             'cron_expr': '0 2 * * *',
                             'retain_count': '5',
                             'host_ids': [str(h.id)],
                             'is_active': 'y'},
                       follow_redirects=False)
    assert resp.status_code == 302

    from app.models import BackupTask
    t = BackupTask.query.filter_by(name='t1').first()
    assert t is not None
    assert t.host_ids == [h.id]
    assert t.cron_expr == '0 2 * * *'
    assert t.next_run is not None

    # 手動執行 — 無 scheduler 模組時應回 501
    monkeypatch.setitem(sys.modules, 'scheduler.ssh_backup', None)
    resp = client.post(f'/it-manager/tasks/{t.id}/run')
    assert resp.status_code == 501
