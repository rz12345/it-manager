"""
DB-backed application settings store.

提供 get_setting / set_setting / get_smtp_cfg，可供 Flask 路由（session=None）
與獨立 scheduler 進程（傳入自訂 SQLAlchemy session）共用。
"""
from __future__ import annotations

DYNAMIC_KEYS = (
    # SMTP 告警
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASS', 'SMTP_FROM',
    'NOTIFY_EMAIL', 'TEST_EMAIL',
    # SSH / Netmiko 逾時
    'SSH_TIMEOUT_SECONDS',
    'NETMIKO_TIMEOUT_SECONDS',
    # 排程併發
    'SCHEDULER_MAX_WORKERS',
    # 密碼政策
    'PW_MIN_LENGTH', 'PW_MIN_UPPER', 'PW_MIN_LOWER', 'PW_MIN_DIGIT',
    'PW_MIN_SPECIAL', 'PW_EXPIRE_DAYS',
)

_DEFAULTS: dict[str, str] = {
    'SMTP_HOST':              '',
    'SMTP_PORT':              '587',
    'SMTP_USER':              '',
    'SMTP_PASS':              '',
    'SMTP_FROM':              '',
    'NOTIFY_EMAIL':           '',
    'TEST_EMAIL':             '',
    'SSH_TIMEOUT_SECONDS':    '30',
    'NETMIKO_TIMEOUT_SECONDS': '60',
    'SCHEDULER_MAX_WORKERS':  '10',
    'PW_MIN_LENGTH':          '8',
    'PW_MIN_UPPER':           '0',
    'PW_MIN_LOWER':           '0',
    'PW_MIN_DIGIT':           '0',
    'PW_MIN_SPECIAL':         '0',
    'PW_EXPIRE_DAYS':         '0',
}


def get_setting(key: str, default: str | None = None, *, session=None) -> str | None:
    """Return the value for *key* from app_settings, or *default* if not found.

    Falls back to _DEFAULTS for known keys when no row exists.
    Returns the fallback silently if the table does not yet exist (e.g. during
    initial `flask db upgrade`).
    """
    from app.models import AppSetting

    try:
        if session is None:
            from app import db as _db
            row = _db.session.get(AppSetting, key)
        else:
            row = session.get(AppSetting, key)
    except Exception:
        return default if default is not None else _DEFAULTS.get(key)

    if row is None:
        return default if default is not None else _DEFAULTS.get(key, '')
    return row.value


def set_setting(key: str, value: str, *, session=None) -> None:
    """Upsert *key* = *value* in app_settings. Caller must commit."""
    from app.models import AppSetting

    if session is None:
        from app import db as _db
        _session = _db.session
    else:
        _session = session

    row = _session.get(AppSetting, key)
    if row is None:
        _session.add(AppSetting(key=key, value=value))
    else:
        row.value = value


def get_smtp_cfg(*, session=None) -> dict:
    """Return an smtp_cfg dict suitable for notifier.send_email()."""
    smtp_user = get_setting('SMTP_USER', session=session) or ''
    return {
        'host':      get_setting('SMTP_HOST', session=session) or '',
        'port':      int(get_setting('SMTP_PORT', session=session) or 587),
        'user':      smtp_user,
        'password':  get_setting('SMTP_PASS', session=session) or '',
        'from_addr': get_setting('SMTP_FROM', session=session) or smtp_user,
    }


def get_ssh_timeout(*, session=None) -> int:
    """SSH 連線逾時秒數（Paramiko）。"""
    return int(get_setting('SSH_TIMEOUT_SECONDS', session=session) or 30)


def get_netmiko_timeout(*, session=None) -> int:
    """Netmiko 連線逾時秒數（網路設備）。"""
    return int(get_setting('NETMIKO_TIMEOUT_SECONDS', session=session) or 60)


def get_scheduler_max_workers(*, session=None) -> int:
    """排程器同時併發備份的執行緒上限。"""
    try:
        n = int(get_setting('SCHEDULER_MAX_WORKERS', session=session) or 10)
    except (TypeError, ValueError):
        n = 10
    return max(1, min(n, 50))
