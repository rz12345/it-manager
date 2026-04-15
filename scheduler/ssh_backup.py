"""Linux 主機 SSH 備份（Paramiko）。

暴露 `run_host_backup(host_id, triggered_by)` 供排程與 Web 手動觸發共用。
"""
from __future__ import annotations

import hashlib
import os
import posixpath
import re
import socket
from datetime import datetime, timezone

import paramiko
from flask import current_app

from app import db
from app.crypto import safe_decrypt
from app.models import BackupRecord, BackupRun, Host
from app.settings_store import get_ssh_timeout


def _sanitize(name: str) -> str:
    return re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_') or 'file'


def _storage_dir(host_id: int) -> str:
    base = current_app.config.get('BACKUP_BASE_PATH')
    path = os.path.join(base, 'hosts', str(host_id))
    os.makedirs(path, exist_ok=True)
    return path


def _expand_glob(sftp: paramiko.SFTPClient, pattern: str) -> list[str]:
    """對遠端路徑展開簡單 Glob（支援目錄層 `*` 萬用）。"""
    if '*' not in pattern and '?' not in pattern:
        return [pattern]

    parts = pattern.split('/')
    results = ['/'] if pattern.startswith('/') else ['']
    for part in parts:
        if not part:
            continue
        next_results = []
        for base in results:
            base_dir = base if base else '.'
            if '*' in part or '?' in part:
                try:
                    entries = sftp.listdir(base_dir)
                except IOError:
                    continue
                regex = re.compile('^' + re.escape(part).replace(r'\*', '.*').replace(r'\?', '.') + '$')
                for e in entries:
                    if regex.match(e):
                        next_results.append(posixpath.join(base, e) if base != '/' else '/' + e)
            else:
                next_results.append(posixpath.join(base, part) if base != '/' else '/' + part)
        results = next_results
    # 過濾：僅保留真實為檔案者
    files = []
    for p in results:
        try:
            st = sftp.stat(p)
            import stat as _stat
            if _stat.S_ISREG(st.st_mode):
                files.append(p)
        except IOError:
            continue
    return files


def _cleanup_old_runs(host_id: int, task_id, retain: int):
    """保留此 (host, task) 下最近 retain 筆 BackupRun，其餘刪除（含實體檔案）。
    task_id 為 None 時清理無任務關聯的 runs（例如 task 已被刪除）。"""
    if retain <= 0:
        return
    q = BackupRun.query.filter_by(target_type='host', host_id=host_id)
    if task_id is None:
        q = q.filter(BackupRun.task_id.is_(None))
    else:
        q = q.filter(BackupRun.task_id == task_id)
    old_runs = q.order_by(BackupRun.started_at.desc()).offset(retain).all()
    for r in old_runs:
        for rec in r.records:
            if rec.storage_path and os.path.exists(rec.storage_path):
                try: os.remove(rec.storage_path)
                except OSError: pass
        db.session.delete(r)


def run_host_backup(host_id: int, task_id: int | None = None,
                    retain_count: int = 10,
                    triggered_by: str = 'schedule') -> BackupRun:
    """執行一次主機備份。建立 BackupRun，連線 SSH 取回所有 file_paths 檔案。"""
    host = Host.query.get(host_id)
    if host is None:
        raise ValueError(f'Host {host_id} 不存在')

    run = BackupRun(target_type='host', host_id=host.id, task_id=task_id,
                    status='running', triggered_by=triggered_by,
                    started_at=datetime.now(timezone.utc))
    db.session.add(run)
    db.session.commit()

    timeout = get_ssh_timeout()
    timestamp = run.started_at.strftime('%Y%m%d_%H%M%S')
    storage_dir = _storage_dir(host.id)
    if host.credential is None:
        run.status = 'failed'
        run.error_message = '主機未綁定驗證'
        run.finished_at = datetime.now(timezone.utc)
        db.session.commit()
        return run
    username = host.credential.username
    password = safe_decrypt(host.credential.password_enc)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    success_count = 0
    fail_count = 0
    run_error = None

    try:
        client.connect(hostname=host.ip_address, port=host.port,
                       username=username, password=password,
                       timeout=timeout, allow_agent=False, look_for_keys=False)
        sftp = client.open_sftp()
        try:
            if not host.file_paths:
                raise RuntimeError('主機尚未設定備份路徑')

            for fp in host.file_paths:
                matched = _expand_glob(sftp, fp.path)
                if not matched:
                    rec = BackupRecord(run_id=run.id, file_path=fp.path,
                                       storage_path='', status='failed',
                                       error_message='路徑不存在或無匹配檔案')
                    db.session.add(rec)
                    fail_count += 1
                    continue

                for remote_path in matched:
                    fname = f'{timestamp}_{_sanitize(remote_path)}'
                    local_path = os.path.join(storage_dir, fname)
                    try:
                        sftp.get(remote_path, local_path)
                        size = os.path.getsize(local_path)
                        with open(local_path, 'rb') as fh:
                            checksum = hashlib.sha256(fh.read()).hexdigest()
                        rec = BackupRecord(run_id=run.id, file_path=remote_path,
                                           storage_path=local_path,
                                           file_size=size, checksum=checksum,
                                           status='success')
                        db.session.add(rec)
                        success_count += 1
                    except Exception as e:
                        rec = BackupRecord(run_id=run.id, file_path=remote_path,
                                           storage_path='', status='failed',
                                           error_message=str(e))
                        db.session.add(rec)
                        fail_count += 1
        finally:
            sftp.close()
    except paramiko.AuthenticationException as e:
        run_error = f'SSH 認證失敗：{e}'
    except (paramiko.SSHException, socket.timeout, OSError) as e:
        run_error = f'SSH 連線失敗：{e}'
    except Exception as e:
        run_error = str(e)
    finally:
        try: client.close()
        except Exception: pass

    # 彙整狀態
    if run_error:
        run.status = 'failed'
        run.error_message = run_error
    elif fail_count == 0 and success_count > 0:
        run.status = 'success'
    elif success_count > 0 and fail_count > 0:
        run.status = 'partial'
    else:
        run.status = 'failed'
        if not run.error_message:
            run.error_message = '沒有任何檔案成功備份'

    run.file_count = success_count
    run.finished_at = datetime.now(timezone.utc)

    db.session.commit()

    # 建立告警
    if run.status in ('failed', 'partial'):
        from app.models import BackupAlert
        severity = 'error' if run.status == 'failed' else 'warning'
        msg = f'{host.name} 備份{ "失敗" if run.status == "failed" else "部分失敗"}'
        if run.error_message:
            msg += f'：{run.error_message}'
        db.session.add(BackupAlert(run_id=run.id, severity=severity, message=msg))
        db.session.commit()
        try:
            from scheduler.notifier import notify_backup_failure
            notify_backup_failure(run, host.name, '主機')
        except Exception:
            pass

    # 清理舊版（以 task 為單位）
    _cleanup_old_runs(host.id, task_id, retain_count or 10)
    db.session.commit()

    return run
