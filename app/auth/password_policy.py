"""
密碼強度驗證工具，依 app_settings 中的 PW_* 規則檢查密碼。
"""
from __future__ import annotations


def get_policy() -> dict:
    """從 DB 讀取目前密碼規則，回傳 dict。"""
    from app.settings_store import get_setting
    return {
        'min_length':  int(get_setting('PW_MIN_LENGTH',  '8') or 8),
        'min_upper':   int(get_setting('PW_MIN_UPPER',   '0') or 0),
        'min_lower':   int(get_setting('PW_MIN_LOWER',   '0') or 0),
        'min_digit':   int(get_setting('PW_MIN_DIGIT',   '0') or 0),
        'min_special': int(get_setting('PW_MIN_SPECIAL', '0') or 0),
        'expire_days': int(get_setting('PW_EXPIRE_DAYS', '0') or 0),
    }


def validate_password(password: str) -> list[str]:
    """依目前密碼規則驗證 password，回傳錯誤訊息清單（空清單表示通過）。"""
    policy = get_policy()
    errors: list[str] = []

    if len(password) < policy['min_length']:
        errors.append(f"密碼長度至少需要 {policy['min_length']} 個字元")

    upper_count = sum(1 for c in password if c.isupper())
    if upper_count < policy['min_upper']:
        errors.append(f"至少需要 {policy['min_upper']} 個大寫英文字母")

    lower_count = sum(1 for c in password if c.islower())
    if lower_count < policy['min_lower']:
        errors.append(f"至少需要 {policy['min_lower']} 個小寫英文字母")

    digit_count = sum(1 for c in password if c.isdigit())
    if digit_count < policy['min_digit']:
        errors.append(f"至少需要 {policy['min_digit']} 個數字")

    special_count = sum(1 for c in password if not c.isalnum())
    if special_count < policy['min_special']:
        errors.append(f"至少需要 {policy['min_special']} 個特殊字元")

    return errors


def policy_description(policy: dict | None = None) -> list[str]:
    """回傳目前密碼規則的人類可讀說明清單（用於前端提示）。"""
    if policy is None:
        policy = get_policy()
    lines: list[str] = []
    lines.append(f"長度至少 {policy['min_length']} 個字元")
    if policy['min_upper']:
        lines.append(f"至少 {policy['min_upper']} 個大寫英文字母")
    if policy['min_lower']:
        lines.append(f"至少 {policy['min_lower']} 個小寫英文字母")
    if policy['min_digit']:
        lines.append(f"至少 {policy['min_digit']} 個數字")
    if policy['min_special']:
        lines.append(f"至少 {policy['min_special']} 個特殊字元")
    return lines
