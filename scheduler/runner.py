"""Cron 排程入口：查詢 next_run 已到的 BackupTask，對其所有目標派送備份。

用法：
    python -m scheduler.runner

將由 crontab 每分鐘觸發一次。單一任務內的多個目標以 ThreadPoolExecutor
併發處理（上限由 SCHEDULER_MAX_WORKERS 設定控制）；整個 runner 透過
data/scheduler.lock 檔案鎖避免重入。
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone


def _compute_next_run(task):
    """重新計算任務的 next_run（cron 模式）。"""
    if task.schedule_mode == 'once':
        return None
    if not task.cron_expr:
        return None
    try:
        from croniter import croniter
        return croniter(task.cron_expr.strip(),
                        datetime.now(timezone.utc)).get_next(datetime)
    except Exception:
        return None


def _acquire_lock(lock_path: str):
    """取得 runner 的獨占檔案鎖；已被持有時回傳 None。

    Linux 使用 fcntl.flock（非阻塞）；Windows 開發環境無 fcntl，降級為
    不加鎖（cron 只在 Linux 部署，不影響實際運行）。
    """
    os.makedirs(os.path.dirname(lock_path) or '.', exist_ok=True)
    fh = open(lock_path, 'w')
    try:
        import fcntl
    except ImportError:
        return fh  # Windows dev: 不加鎖
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        fh.close()
        return None
    fh.write(str(os.getpid()))
    fh.flush()
    return fh


def _release_lock(fh):
    if fh is None:
        return
    try:
        import fcntl
        try: fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except Exception: pass
    except ImportError:
        pass
    try: fh.close()
    except Exception: pass


def _run_one_target(app, target_type: str, target_id: int,
                    target_name: str, task_id: int, retain_count: int):
    """子執行緒入口：push app_context，跑單一目標備份。"""
    from app import db
    from scheduler.ssh_backup import run_host_backup
    from scheduler.netmiko_backup import run_device_backup

    with app.app_context():
        try:
            if target_type == 'host':
                r = run_host_backup(target_id, task_id=task_id,
                                    retain_count=retain_count,
                                    triggered_by='schedule')
            else:
                r = run_device_backup(target_id, task_id=task_id,
                                      retain_count=retain_count,
                                      triggered_by='schedule')
            return (target_type, target_name, r.status, None)
        except Exception as e:
            try: db.session.rollback()
            except Exception: pass
            return (target_type, target_name, 'error', str(e))


def main() -> int:
    from app import create_app, db
    from app.models import BackupTask
    from app.settings_store import get_scheduler_max_workers

    app = create_app()

    _base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    lock_path = os.path.join(_base_dir, 'data', 'scheduler.lock')
    lock_fh = _acquire_lock(lock_path)
    if lock_fh is None:
        print('[runner] another instance is running — skip this tick')
        return 0

    try:
        with app.app_context():
            now = datetime.now(timezone.utc)
            max_workers = get_scheduler_max_workers()

            # 清理 orphan 殘影：status=running 但已超過合理時限的舊紀錄
            # （發生在 runner 被中斷、Netmiko hang 或 Windows 無 flock 時的重覆派送）
            from app.settings_store import (get_netmiko_timeout,
                                            get_ssh_timeout)
            from app.models import BackupRun
            from datetime import timedelta
            max_allowed = max(get_netmiko_timeout(), get_ssh_timeout()) * 3
            cutoff = now - timedelta(seconds=max_allowed)
            orphans = (BackupRun.query
                       .filter(BackupRun.status == 'running',
                               BackupRun.started_at < cutoff)
                       .all())
            if orphans:
                for r in orphans:
                    r.status = 'failed'
                    r.finished_at = now
                    r.error_message = (r.error_message or
                                       'orphaned: runner 中斷或重入，由下一輪清理')
                db.session.commit()
                print(f'[runner] cleaned {len(orphans)} orphaned running rows')

            tasks = (BackupTask.query
                     .filter(BackupTask.is_active.is_(True),
                             BackupTask.next_run.isnot(None),
                             BackupTask.next_run <= now)
                     .all())

            print(f'[runner] {now.isoformat()} — tasks={len(tasks)} '
                  f'max_workers={max_workers}')

            for task in tasks:
                targets = list(task.targets)
                print(f'  task #{task.id} {task.name} ({len(targets)} targets)')

                # 先解析每個 target 的 (type, id, name)，避免在子執行緒
                # 中再存取 task.targets（lazy relationship 可能需要主
                # session，跨執行緒不安全）。
                plan = []
                for t in targets:
                    if t.target_type == 'host' and t.host:
                        plan.append(('host', t.host.id, t.target_name))
                    elif t.target_type == 'device' and t.device:
                        plan.append(('device', t.device.id, t.target_name))

                success = failed = 0
                workers = max(1, min(max_workers, len(plan) or 1))

                with ThreadPoolExecutor(max_workers=workers) as pool:
                    futures = [
                        pool.submit(_run_one_target, app, ttype, tid, tname,
                                    task.id, task.retain_count)
                        for (ttype, tid, tname) in plan
                    ]
                    for fut in as_completed(futures):
                        ttype, tname, status, err = fut.result()
                        if status == 'success':
                            success += 1
                        else:
                            failed += 1
                        if err:
                            print(f'    {ttype}:{tname} → ERROR {err}',
                                  file=sys.stderr)
                        else:
                            print(f'    {ttype}:{tname} → {status}')

                # 更新任務統計（主執行緒 session）
                task.last_run = datetime.now(timezone.utc)
                if failed == 0 and success > 0:
                    task.last_status = 'success'
                elif success > 0 and failed > 0:
                    task.last_status = 'partial'
                else:
                    task.last_status = 'failed'

                if task.schedule_mode == 'once':
                    task.is_active = False
                    task.next_run = None
                else:
                    task.next_run = _compute_next_run(task)

                db.session.commit()

        return 0
    finally:
        _release_lock(lock_fh)


if __name__ == '__main__':
    sys.exit(main())
