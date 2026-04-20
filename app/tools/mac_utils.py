"""MAC address 格式工具。

內部標準格式：12 個小寫 hex 字元（無分隔）。
輸出時依廠商需求轉成對應格式（Cisco 點號、Aruba 冒號等）。
"""
from __future__ import annotations

import re

_HEX_ONLY = re.compile(r'[^0-9a-fA-F]')


def normalize_mac(raw: str) -> str:
    """將任意格式 MAC 正規化為 12 字元小寫 hex 字串。

    接受：aa:bb:cc:dd:ee:ff / AA-BB-CC-DD-EE-FF / aabb.ccdd.eeff /
          aabbccddeeff 等；不合法輸入 raise ValueError。
    """
    if raw is None:
        raise ValueError('MAC 不可為空')
    stripped = _HEX_ONLY.sub('', raw)
    if len(stripped) != 12:
        raise ValueError(f'MAC 格式錯誤：{raw!r}')
    return stripped.lower()


def format_cisco(mac12: str) -> str:
    """aabb.ccdd.eeff"""
    return f'{mac12[0:4]}.{mac12[4:8]}.{mac12[8:12]}'


def format_colon(mac12: str) -> str:
    """aa:bb:cc:dd:ee:ff"""
    return ':'.join(mac12[i:i+2] for i in range(0, 12, 2))


def format_dash(mac12: str) -> str:
    """aa-bb-cc-dd-ee-ff"""
    return '-'.join(mac12[i:i+2] for i in range(0, 12, 2))


def format_for_vendor(mac12: str, vendor: str) -> str:
    """依 vendor 回傳該設備習慣的 MAC 字串格式。"""
    if vendor == 'cisco_ios':
        return format_cisco(mac12)
    # aruba_os / zyxel_os 與多數其他廠商 CLI 接受冒號分隔
    return format_colon(mac12)


def mac_equals(a: str, b: str) -> bool:
    """忽略格式差異比較兩個 MAC 是否相同。"""
    try:
        return normalize_mac(a) == normalize_mac(b)
    except ValueError:
        return False
