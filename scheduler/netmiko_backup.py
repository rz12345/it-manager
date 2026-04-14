"""網路設備備份（Netmiko，取得 running-config）。

暴露 `run_device_backup(device_id, triggered_by)`。
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from flask import current_app

from app import db
from app.crypto import safe_decrypt
from app.models import BackupRecord, BackupRun, Device
from app.settings_store import get_netmiko_timeout


def _storage_dir(device_id: int) -> str:
    base = current_app.config.get('BACKUP_BASE_PATH')
    path = os.path.join(base, 'devices', str(device_id))
    os.makedirs(path, exist_ok=True)
    return path


def _cleanup_old_runs(device_id: int, task_id, retain: int):
    if retain <= 0:
        return
    q = BackupRun.query.filter_by(target_type='device', device_id=device_id)
    if task_id is None:
        q = q.filter(BackupRun.task_id.is_(None))
    else:
        q = q.filter(BackupRun.task_id == task_id)
    old = q.order_by(BackupRun.started_at.desc()).offset(retain).all()
    for r in old:
        for rec in r.records:
            if rec.storage_path and os.path.exists(rec.storage_path):
                try: os.remove(rec.storage_path)
                except OSError: pass
        db.session.delete(r)


def run_device_backup(device_id: int, task_id: int | None = None,
                      retain_count: int = 10,
                      triggered_by: str = 'schedule') -> BackupRun:
    from netmiko import ConnectHandler
    from netmiko.exceptions import (NetmikoAuthenticationException,
                                    NetmikoTimeoutException)

    device = Device.query.get(device_id)
    if device is None:
        raise ValueError(f'Device {device_id} 不存在')

    run = BackupRun(target_type='device', device_id=device.id, task_id=task_id,
                    status='running', triggered_by=triggered_by,
                    started_at=datetime.now(timezone.utc))
    db.session.add(run)
    db.session.commit()

    timeout = get_netmiko_timeout()
    timestamp = run.started_at.strftime('%Y%m%d_%H%M%S')
    storage_dir = _storage_dir(device.id)

    password = safe_decrypt(device.password_enc)
    enable_pw = safe_decrypt(device.enable_password_enc or '')
    conn_args = {
        'device_type': device.vendor,
        'host':        device.ip_address,
        'port':        device.port,
        'username':    device.username,
        'password':    password,
        'timeout':     timeout,
    }
    if enable_pw:
        conn_args['secret'] = enable_pw

    run_error = None
    command = device.effective_command
    output = None

    # 依 vendor 送一條 paging-off 指令；未知 vendor 則跳過（Netmiko 多數
    # driver 會在連線建立時自動關 paging）。
    _PAGING_BY_VENDOR = {
        'cisco_ios':      'terminal length 0',
        'cisco_xe':       'terminal length 0',
        'cisco_nxos':     'terminal length 0',
        'cisco_asa':      'terminal pager 0',
        'aruba_os':       'no page',
        'aruba_osswitch': 'no page',
        'hp_procurve':    'no page',
        'paloalto_panos': 'set cli pager off',
    }
    paging_cmd = _PAGING_BY_VENDOR.get(device.vendor)

    try:
        with ConnectHandler(**conn_args) as conn:
            if enable_pw:
                try: conn.enable()
                except Exception: pass
            if paging_cmd:
                try:
                    conn.send_command_timing(paging_cmd, read_timeout=10,
                                             strip_prompt=False,
                                             strip_command=False)
                except Exception:
                    pass
            try:
                output = conn.send_command(command, read_timeout=timeout)
            except Exception:
                # prompt 偵測失敗 → 改用 timing 模式（不靠 prompt，以輸出
                # 靜默判斷結束），對 Aruba/老舊韌體最可靠
                output = conn.send_command_timing(command,
                                                  read_timeout=timeout,
                                                  last_read=4.0)
    except NetmikoAuthenticationException as e:
        run_error = f'認證失敗：{e}'
    except NetmikoTimeoutException as e:
        run_error = f'連線逾時：{e}'
    except Exception as e:
        run_error = str(e)

    if run_error:
        run.status = 'failed'
        run.error_message = run_error
        run.file_count = 0
    else:
        fname = f'{timestamp}_running.cfg'
        local_path = os.path.join(storage_dir, fname)
        data = (output or '').encode('utf-8')
        with open(local_path, 'wb') as fh:
            fh.write(data)
        checksum = hashlib.sha256(data).hexdigest()
        rec = BackupRecord(run_id=run.id, file_path='running-config',
                           storage_path=local_path, file_size=len(data),
                           checksum=checksum, status='success')
        db.session.add(rec)
        run.status = 'success'
        run.file_count = 1

    run.finished_at = datetime.now(timezone.utc)
    db.session.commit()

    if run.status in ('failed', 'partial'):
        from app.models import BackupAlert
        severity = 'error' if run.status == 'failed' else 'warning'
        msg = f'{device.name} 備份失敗'
        if run.error_message:
            msg += f'：{run.error_message}'
        db.session.add(BackupAlert(run_id=run.id, severity=severity, message=msg))
        db.session.commit()
        try:
            from scheduler.notifier import notify_backup_failure
            notify_backup_failure(run, device.name, '設備')
        except Exception:
            pass

    _cleanup_old_runs(device.id, task_id, retain_count or 10)
    db.session.commit()

    return run
