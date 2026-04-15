"""Cron 排程入口：依 task.type 分派至對應 handler。

支援兩種任務型別：
  - backup : ssh_backup.run_host_backup / netmiko_backup.run_device_backup
  - email  : email_task.run_email_task

每分鐘由 crontab 觸發一次。備份任務內的多目標以 ThreadPoolExecutor 併發；
整個 runner 透過 data/scheduler.lock 檔案鎖避免重入。
"""
from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone


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
    """取得 runner 的獨占檔案鎖；已被持有時回傳 None。"""
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


def _run_one_backup_target(app, target_type, target_id, target_name,
                           task_id, retain_count):
    """子執行緒：單一備份目標（host 或 device）。"""
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


def _dispatch_backup_task(app, task, max_workers: int) -> tuple[int, int]:
    """派送 backup 任務的所有目標；回傳 (success, failed)。"""
    targets = list(task.targets)
    print(f'  [backup] task #{task.id} {task.name} ({len(targets)} targets)')

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
            pool.submit(_run_one_backup_target, app, ttype, tid, tname,
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
                print(f'    {ttype}:{tname} → ERROR {err}', file=sys.stderr)
            else:
                print(f'    {ttype}:{tname} → {status}')
    return success, failed


def _dispatch_email_task(task) -> tuple[int, int]:
    """派送 email 任務（在主執行緒跑；Playwright 無法安全多執行緒）。

    回傳 (success, failed)：success=1 若 run.status in {'success'}，
    否則 failed=1；partial 視為部分失敗以便 last_status 正確。
    """
    from scheduler.email_task import run_email_task

    print(f'  [email] task #{task.id} {task.name}')
    try:
        run = run_email_task(task.id, triggered_by='schedule')
    except Exception as e:
        print(f'    ERROR {e}', file=sys.stderr)
        return 0, 1

    print(f'    status={run.status} sent={run.file_count}')
    if run.status == 'success':
        return 1, 0
    if run.status == 'partial':
        return 1, 1
    return 0, 1


def _clean_orphan_runs(now: datetime) -> int:
    """清理 status='running' 但已超時的 TaskRun。"""
    from app import db
    from app.models import TaskRun
    from app.settings_store import get_netmiko_timeout, get_ssh_timeout

    max_allowed = max(get_netmiko_timeout(), get_ssh_timeout(), 300) * 3
    cutoff = now - timedelta(seconds=max_allowed)
    orphans = (TaskRun.query
               .filter(TaskRun.status == 'running',
                       TaskRun.started_at < cutoff)
               .all())
    for r in orphans:
        r.status = 'failed'
        r.finished_at = now
        r.error_message = (r.error_message or
                           'orphaned: runner 中斷或重入，由下一輪清理')
    if orphans:
        db.session.commit()
    return len(orphans)


def main() -> int:
    from app import create_app, db
    from app.models import Task
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

            cleaned = _clean_orphan_runs(now)
            if cleaned:
                print(f'[runner] cleaned {cleaned} orphaned running rows')

            tasks = (Task.query
                     .filter(Task.is_active.is_(True),
                             Task.next_run.isnot(None),
                             Task.next_run <= now)
                     .all())

            print(f'[runner] {now.isoformat()} — tasks={len(tasks)} '
                  f'max_workers={max_workers}')

            for task in tasks:
                if task.type == 'backup':
                    success, failed = _dispatch_backup_task(app, task, max_workers)
                elif task.type == 'email':
                    success, failed = _dispatch_email_task(task)
                else:
                    print(f'  [skip] task #{task.id} unknown type {task.type!r}',
                          file=sys.stderr)
                    continue

                # 任務統計（主執行緒 session）
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
