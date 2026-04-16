"""排程相關共用工具：統一 cron 下次執行時間計算，確保 UI 與 runner 一致。"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo


def get_display_tz() -> ZoneInfo:
    try:
        from flask import current_app
        tz_name = current_app.config.get('DISPLAY_TZ', 'Asia/Taipei')
    except Exception:
        tz_name = os.environ.get('DISPLAY_TZ', 'Asia/Taipei')
    return ZoneInfo(tz_name)


def compute_next_run(task):
    """以 DISPLAY_TZ 為基準計算 cron 的下次執行時間，回傳 UTC naive datetime。

    一次性任務回傳 ``task.scheduled_at``；無 cron 或解析失敗回傳 None。
    """
    if task.schedule_mode == 'once':
        return task.scheduled_at
    if not task.cron_expr:
        return None
    try:
        from croniter import croniter
        tz = get_display_tz()
        now_local = datetime.now(tz)
        nxt_local = croniter(task.cron_expr.strip(), now_local).get_next(datetime)
        return nxt_local.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None
