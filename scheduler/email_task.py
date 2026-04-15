"""Email 型任務處理器：依任務綁定的模板逐一送信，產生 EmailRun 紀錄。

暴露 `run_email_task(task_id, triggered_by)`，簽名與 ssh/netmiko 的
`run_host_backup / run_device_backup` 對齊，供 scheduler/runner.py 與 Web 手動觸發共用。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app import db
from app.models import EmailRun, EmailTask, Scraper, ScraperLog
from app.settings_store import get_smtp_cfg
from scheduler.mailer import send_email
from scheduler.scraper import scrape_and_extract


def _fetch_scraper_vars(tmpl) -> tuple[dict, list[str]]:
    """解析模板綁定的爬蟲變數（失敗回退到 last_content）。"""
    scraper_vars_map = tmpl.scraper_vars or {}
    if not scraper_vars_map:
        return {}, []

    resolved = {}
    errors = []
    now = datetime.utcnow()

    for var_name, scraper_id in scraper_vars_map.items():
        scraper = db.session.get(Scraper, scraper_id)
        if scraper is None:
            resolved[var_name] = ''
            errors.append(f'[scraper_vars] 變數 {var_name!r}: 爬蟲 #{scraper_id} 不存在')
            continue

        log = ScraperLog(scraper_id=scraper.id, checked_at=now)
        try:
            content, _ = scrape_and_extract(
                scraper.url, scraper.extract_type, scraper.extract_pattern
            )
            log.status = 'success'
            log.content = content
            scraper.last_content = content
            scraper.last_checked = now
            resolved[var_name] = content
        except Exception as exc:
            log.status = 'error'
            log.error_message = str(exc)
            scraper.last_checked = now
            fallback = scraper.last_content or ''
            resolved[var_name] = fallback
            errors.append(f'[scraper_vars] 變數 {var_name!r} 擷取失敗，使用快取'
                          f'（{"有" if fallback else "無"}）：{exc}')
        db.session.add(log)

    return resolved, errors


def run_email_task(task_id: int, triggered_by: str = 'schedule') -> EmailRun:
    """對單一 Email 任務執行一次，遍歷其綁定的所有模板送信。

    回傳 EmailRun；status: success / partial / failed。
    """
    task: EmailTask = EmailTask.query.get(task_id)
    if task is None:
        raise ValueError(f'EmailTask #{task_id} not found')

    run = EmailRun(
        task_id=task.id,
        recipients=task.recipients or '',
        triggered_by=triggered_by,
        status='running',
    )
    db.session.add(run)
    db.session.commit()

    smtp_cfg = get_smtp_cfg()
    errors: list[str] = []
    sent_count = 0

    for tt in task.task_templates:
        tmpl = tt.template
        if tmpl is None:
            errors.append(f'模板 #{tt.template_id} 不存在')
            continue

        scraper_vars, scraper_errs = _fetch_scraper_vars(tmpl)
        errors.extend(scraper_errs)
        merged_vars = {**(task.template_vars or {}), **scraper_vars}

        attachments = [
            {'filename': a.filename, 'storage_path': a.storage_path}
            for a in tmpl.attachments
        ]
        task_dict = {
            'recipients': task.recipients or '',
            'subject': tmpl.subject,
            'template_vars': merged_vars,
        }

        try:
            send_email(task_dict, tmpl.body_path, attachments, smtp_cfg)
            sent_count += 1
        except Exception as exc:
            errors.append(f'[模板 {tmpl.name}] {exc}')

    run.finished_at = datetime.now(timezone.utc)
    if errors and sent_count == 0:
        run.status = 'failed'
    elif errors and sent_count > 0:
        run.status = 'partial'
    else:
        run.status = 'success'
    run.error_message = '\n'.join(errors) if errors else None
    run.file_count = sent_count

    db.session.commit()

    from scheduler.notifier import notify_task_failure
    notify_task_failure(run, task.name, 'email')

    return run
