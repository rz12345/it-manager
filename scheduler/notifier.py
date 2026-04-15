"""SMTP 失敗告警通知（從 app_settings 讀取 SMTP 設定）。"""
from __future__ import annotations

import smtplib
from email.message import EmailMessage

from app.settings_store import get_setting, get_smtp_cfg


def send_email(subject: str, body: str, to_addr: str | None = None) -> tuple[bool, str]:
    """寄送告警信。成功回傳 (True, '')，失敗回傳 (False, error_message)。"""
    cfg = get_smtp_cfg()
    recipient = to_addr or (get_setting('NOTIFY_EMAIL') or '')

    if not cfg['host'] or not cfg['from_addr'] or not recipient:
        return False, 'SMTP 或收件人未設定，略過寄送'

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = cfg['from_addr']
    msg['To'] = recipient
    msg.set_content(body)

    try:
        with smtplib.SMTP(cfg['host'], cfg['port'], timeout=20) as s:
            s.ehlo()
            try:
                s.starttls()
                s.ehlo()
            except smtplib.SMTPException:
                pass
            if cfg['user'] and cfg['password']:
                s.login(cfg['user'], cfg['password'])
            s.send_message(msg)
        return True, ''
    except Exception as e:
        return False, str(e)


def notify_backup_failure(run, target_name: str, target_type: str) -> None:
    """備份失敗/部分失敗時寄發告警信。"""
    if run.status not in ('failed', 'partial'):
        return
    status_label = {'failed': '失敗', 'partial': '部分失敗'}.get(run.status, run.status)
    subject = f'[IT Manager] {target_type} 備份{status_label}：{target_name}'
    lines = [
        f'目標：{target_type} / {target_name}',
        f'狀態：{status_label}',
        f'開始：{run.started_at}',
        f'結束：{run.finished_at}',
        f'檔案數：{run.file_count}',
    ]
    if run.error_message:
        lines.append(f'錯誤訊息：{run.error_message}')
    for rec in run.records:
        if rec.status == 'failed':
            lines.append(f'  - 失敗檔案：{rec.file_path}  {rec.error_message or ""}')
    send_email(subject, '\n'.join(lines))


def notify_email_failure(run, task_name: str) -> None:
    """Email 任務失敗/部分失敗時寄發告警信。"""
    if run.status not in ('failed', 'partial'):
        return
    status_label = {'failed': '失敗', 'partial': '部分失敗'}.get(run.status, run.status)
    subject = f'[IT Manager] 郵件任務{status_label}：{task_name}'
    lines = [
        f'任務：{task_name}',
        f'狀態：{status_label}',
        f'開始：{run.started_at}',
        f'結束：{run.finished_at}',
        f'成功送出：{run.file_count} 封',
        f'收件人：{run.recipients}',
    ]
    if run.error_message:
        lines.append('')
        lines.append('錯誤訊息：')
        lines.append(run.error_message)
    send_email(subject, '\n'.join(lines))


def notify_task_failure(run, task_name: str, task_type: str) -> None:
    """統一入口：依 task_type 分派到 backup / email 告警。"""
    if task_type == 'email':
        notify_email_failure(run, task_name)
    else:
        notify_backup_failure(run, task_name, task_type)
