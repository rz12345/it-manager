"""SMTP 郵件寄送（email 型任務用）。

接受 task dict + 模板檔 + 附件 + smtp_cfg，組裝 MIMEMultipart 寄出；
失敗重試一次。自 task-manager 移植。
"""
import os
import time
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape


def _nl2br(value):
    return Markup(escape(value).replace('\n', Markup('<br>\n')))


def _plain_to_html(text):
    import html as _html
    escaped = _html.escape(text)
    body = escaped.replace('\n', '<br>\n')
    return f'<html><body style="font-family:sans-serif;white-space:pre-wrap">{body}</body></html>'


def _auto_vars() -> dict:
    from datetime import datetime as _dt
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(os.environ.get('DISPLAY_TZ', 'Asia/Taipei'))
    now = _dt.now(tz)
    return {
        'date':     now.strftime('%Y-%m-%d'),
        'datetime': now.strftime('%Y-%m-%d %H:%M'),
        'year':     str(now.year),
        'month':    str(now.month),
        'day':      str(now.day),
    }


def _build_message(from_addr, task, template_path, attachments):
    template_dir = os.path.dirname(template_path)
    template_file = os.path.basename(template_path)

    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(['html']),
    )
    env.filters['nl2br'] = _nl2br
    tmpl = env.get_template(template_file)
    render_vars = {**_auto_vars(), **(task.get('template_vars') or {})}
    body = tmpl.render(**render_vars)

    import re as _re
    html_body = body if _re.search(r'<[a-zA-Z]', body) else _plain_to_html(body)

    msg = MIMEMultipart('mixed')
    msg['From'] = from_addr
    msg['To'] = task['recipients']
    from jinja2 import Template as _JinjaTemplate
    msg['Subject'] = _JinjaTemplate(task['subject']).render(**render_vars)
    msg.attach(MIMEText(html_body, 'html', 'utf-8'))

    for att in attachments:
        if not os.path.exists(att['storage_path']):
            continue
        with open(att['storage_path'], 'rb') as f:
            part = MIMEApplication(f.read())
        part.add_header('Content-Disposition', 'attachment', filename=att['filename'])
        msg.attach(part)

    return msg


def _smtp_connect(host, port, user, password):
    if port == 465:
        conn = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        conn = smtplib.SMTP(host, port, timeout=30)
        conn.starttls()
    if user and password:
        conn.login(user, password)
    return conn


def send_email(task: dict, template_path: str, attachments: list, smtp_cfg: dict) -> None:
    """寄送單封信（失敗重試一次）。

    task: dict with keys: recipients, subject, template_vars
    smtp_cfg: dict with keys: host, port, user, password, from_addr
    """
    host = smtp_cfg['host']
    port = smtp_cfg['port']
    user = smtp_cfg['user']
    password = smtp_cfg['password']
    from_addr = smtp_cfg.get('from_addr') or user

    recipients = [r.strip() for r in task['recipients'].split(',') if r.strip()]

    last_exc = None
    for attempt in range(2):
        try:
            conn = _smtp_connect(host, port, user, password)
            msg = _build_message(from_addr, task, template_path, attachments)
            conn.sendmail(from_addr or user, recipients, msg.as_string())
            conn.quit()
            return
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                time.sleep(5)
    raise last_exc
