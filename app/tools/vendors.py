"""廠商指令與輸出解析。

每個 vendor 提供：
- build_mac_lookup_cmds(mac12) → 可依序嘗試的 CLI 命令字串列表
- build_neighbor_cmds(port)   → 可依序嘗試的鄰居查詢命令（先 CDP 再 LLDP）
- parse_mac_row(output, mac12)    → {'port': str, 'vlan': str|None} | None
- parse_neighbor(output)          → {'system_name': str|None,
                                     'mgmt_ip': str|None,
                                     'remote_port': str|None} | None

解析採寬鬆比對（部分 vendor CLI 輸出略有差異），解析失敗回傳 None；
上層視為「該跳為 edge / 資訊不足，停止追蹤」。
"""
from __future__ import annotations

import re
from typing import Optional

from app.tools.mac_utils import format_cisco, format_colon, normalize_mac

_IP_RE = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')
_MAC_ANY_RE = re.compile(r'[0-9a-fA-F]{2}[:\-.]?[0-9a-fA-F]{2}'
                         r'[:\-.]?[0-9a-fA-F]{2}[:\-.]?[0-9a-fA-F]{2}'
                         r'[:\-.]?[0-9a-fA-F]{2}[:\-.]?[0-9a-fA-F]{2}')
_VLAN_RE = re.compile(r'^\d{1,4}$')


# ─── 命令建立 ───

def build_mac_lookup_cmds(vendor: str, mac12: str) -> list[str]:
    """回傳可依序嘗試的 MAC 查詢命令（第一個有解析結果者即用）。

    Aruba 依機型有兩種語法：
    - AOS-CX：`show mac-address-table address <mac>`
    - AOS-S / ProCurve：`show mac-address <mac>`
    皆以冒號格式帶入；兩個都試可覆蓋大多數情境。
    """
    if vendor == 'cisco_ios':
        return [f'show mac address-table address {format_cisco(mac12)}']
    if vendor == 'aruba_os':
        colon = format_colon(mac12)
        return [
            f'show mac-address-table address {colon}',
            f'show mac-address {colon}',
        ]
    if vendor == 'zyxel_os':
        return [f'show mac address-table mac {format_colon(mac12)}']
    return []


_LAG_PATTERNS = {
    'cisco_ios': re.compile(r'^(po|port-?channel)(\d+)$', re.IGNORECASE),
    'aruba_os':  re.compile(r'^(lag|trk|trunk)(\d+)$', re.IGNORECASE),
}


def is_lag_port(vendor: str, port: str) -> bool:
    pat = _LAG_PATTERNS.get(vendor)
    return bool(pat and pat.match(port.strip()))


def build_lag_members_cmds(vendor: str, port: str) -> list[str]:
    """回傳取得 LAG / Port-Channel 實體成員 port 的 CLI 命令。"""
    port = port.strip()
    if vendor == 'cisco_ios':
        m = _LAG_PATTERNS['cisco_ios'].match(port)
        if not m:
            return []
        n = m.group(2)
        return [
            f'show etherchannel {n} summary',
            f'show interfaces port-channel {n}',
        ]
    if vendor == 'aruba_os':
        m = _LAG_PATTERNS['aruba_os'].match(port)
        if not m:
            return []
        kind, n = m.group(1).lower(), m.group(2)
        if kind == 'lag':
            # AOS-CX
            return [
                f'show lacp aggregates lag{n}',
                f'show interface lag {n}',
            ]
        # ProCurve (Trk/Trunk)
        return ['show trunks', 'show lacp']
    return []


def parse_lag_members(vendor: str, output: str, lag_port: str) -> list[str]:
    """從 LAG 展開命令的輸出中擷取成員 port 名稱。"""
    if not output:
        return []
    lag = lag_port.strip()

    if vendor == 'cisco_ios':
        # 範例：Po13(SU) LACP Gi1/0/24(P) Gi1/0/25(P)
        members: list[str] = []
        for line in output.splitlines():
            if not re.search(r'\b' + re.escape(lag) + r'\b', line,
                             re.IGNORECASE):
                continue
            for m in re.finditer(
                    r'\b([A-Za-z]{2,}[\d/]+)\s*\([A-Za-z]+\)', line):
                members.append(m.group(1))
        # 去重保序
        seen: set[str] = set()
        out: list[str] = []
        for p in members:
            if p.lower() == lag.lower():
                continue
            if p not in seen:
                seen.add(p)
                out.append(p)
        return out

    if vendor == 'aruba_os':
        m = _LAG_PATTERNS['aruba_os'].match(lag)
        if not m:
            return []
        kind, n = m.group(1).lower(), m.group(2)

        # AOS-CX: "Aggregated-interfaces : 1/1/49 1/1/50"
        m2 = re.search(
            r'Aggregated[-\s]*interfaces\s*[:\-]\s*(.+)',
            output, re.IGNORECASE)
        if m2:
            return [p for p in m2.group(1).split() if p]

        # ProCurve `show trunks`：
        #   Port | Name         Type       | Group Type
        #   25   | link-agg     100/1000T  | Trk1  LACP
        target = f'Trk{n}'
        members2: list[str] = []
        for line in output.splitlines():
            if not re.search(r'\b' + re.escape(target) + r'\b', line,
                             re.IGNORECASE):
                continue
            parts = [p.strip() for p in re.split(r'\|', line)]
            if parts and parts[0]:
                first = parts[0].split()
                if first and re.match(r'^[\w/]+$', first[0]):
                    members2.append(first[0])
        if members2:
            return members2

        # ProCurve `show lacp`：第一欄 Port、某欄顯示 Trk1
        for line in output.splitlines():
            if not re.search(r'\b' + re.escape(target) + r'\b', line,
                             re.IGNORECASE):
                continue
            tokens = line.split()
            if tokens and re.match(r'^[\w/]+$', tokens[0]):
                members2.append(tokens[0])
        return members2

    return []


def build_port_desc_cmds(vendor: str, port: str) -> list[str]:
    """回傳取得 interface description 的 CLI 命令（可多個，依序嘗試）。"""
    port = port.strip()
    if vendor == 'cisco_ios':
        return [f'show interfaces {port} description']
    if vendor == 'aruba_os':
        # AOS-CX 對 LAG 需要 "interface lag 13"（有空白）；物理 port 則直接帶原名
        cmds = [f'show running-config interface {port}']
        m = _LAG_PATTERNS['aruba_os'].match(port)
        if m:
            kind, n = m.group(1).lower(), m.group(2)
            if kind == 'lag':
                cmds.append(f'show running-config interface lag {n}')
        return cmds
    if vendor == 'zyxel_os':
        return [
            f'show running-config interface port {port}',
            f'show interface port {port}',
        ]
    return []


def parse_port_desc(vendor: str, output: str, port: str) -> Optional[str]:
    """從 interface 描述命令的輸出中擷取 description 字串。"""
    if not output:
        return None
    low = output.lower()
    for pat in ('invalid input', 'unknown command', 'ambiguous',
                'no such', 'not found'):
        if pat in low:
            return None

    if vendor == 'cisco_ios':
        # `show interfaces X description` 為表格式：
        #   Interface    Status    Protocol   Description
        #   Gi1/0/24     up        up         UPLink to SW-CORE
        for line in output.splitlines():
            s = line.strip()
            if not s or s.startswith('-'):
                continue
            low_s = s.lower()
            if low_s.startswith('interface') and 'description' in low_s:
                continue
            parts = s.split(None, 3)
            if len(parts) < 4:
                continue
            if parts[0].lower() != port.lower():
                continue
            return parts[3].strip() or None
        return None

    # Aruba / Zyxel：從 running-config 片段找 `description <text>` 行
    for line in output.splitlines():
        m = re.match(r'^\s*description\s+(.+?)\s*$', line, re.IGNORECASE)
        if m:
            desc = m.group(1).strip().strip('"').strip("'").strip()
            if desc:
                return desc
    return None


def build_neighbor_cmds(vendor: str, port: str) -> list[str]:
    """回傳可依序嘗試的鄰居查詢命令（先試 CDP 再試 LLDP；Aruba/Zyxel 只有 LLDP）。"""
    port = port.strip()
    if vendor == 'cisco_ios':
        return [
            f'show cdp neighbors {port} detail',
            f'show lldp neighbors {port} detail',
        ]
    if vendor == 'aruba_os':
        return [
            f'show lldp neighbor-info {port}',        # AOS-CX
            f'show lldp info remote-device {port}',   # ProCurve / AOS-S
        ]
    if vendor == 'zyxel_os':
        return [
            f'show lldp ne interface port {port}',
            f'show lldp neighbor interface port {port}',
        ]
    return []


# ─── MAC 行解析 ───

def parse_mac_row(vendor: str, output: str, mac12: str) -> Optional[dict]:
    """從 MAC lookup 指令輸出中擷取 VLAN 與 port。依 vendor 使用不同規則。

    Cisco：`VLAN MAC TYPE PORT`（VLAN 先、port 通常含字母如 Gi1/0/24）
    Aruba：`MAC PORT VLAN`（port 與 VLAN 皆純數字，靠欄位順序區分）
    Zyxel：欄位依機型有差異，採寬鬆規則（port 含字母優先；否則後備）
    """
    if not output:
        return None
    mac12 = mac12.lower()

    for raw_line in output.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        # 該行需含此 MAC（任何格式）
        tokens_all = stripped.split()
        mac_index = -1
        for i, t in enumerate(tokens_all):
            if _is_same_mac(t, mac12):
                mac_index = i
                break
        # 容許整行某個 substring 包含 MAC（例如 "Address:aa:bb:cc:..."）
        if mac_index < 0:
            for m in _MAC_ANY_RE.findall(stripped):
                try:
                    if normalize_mac(m) == mac12:
                        mac_index = 0
                        break
                except ValueError:
                    continue
        if mac_index < 0:
            continue
        # 真正的資料列 MAC 通常在前 3 個 token 內（Cisco 是第 2 個、Aruba/Zyxel
        # 是第 1 個）；若 MAC 出現在靠後位置，多半是 title/header 內嵌說明
        if mac_index > 2:
            continue

        tokens = stripped.split()
        tokens = [t for t in tokens if not _is_same_mac(t, mac12)]
        tokens = [t for t in tokens
                  if t.lower() not in
                  ('dynamic', 'static', 'learned', 'self', '---', '--',
                   'type', 'forward', 'secure', '|')]
        if not tokens:
            continue

        result = _extract_port_vlan_by_vendor(vendor, tokens)
        if result and result.get('port'):
            return result
    return None


def _extract_port_vlan_by_vendor(vendor: str, tokens: list[str]) -> Optional[dict]:
    numeric = [t for t in tokens if _VLAN_RE.match(t) and 1 <= int(t) <= 4094]
    port_like = [t for t in tokens if re.search(r'[A-Za-z/]', t)]

    if vendor == 'cisco_ios':
        # VLAN 通常是第一個純數字；port 帶字母
        vlan = numeric[0] if numeric else None
        port = port_like[-1] if port_like else (tokens[-1] if tokens else None)
        return {'port': port, 'vlan': vlan}

    if vendor == 'aruba_os':
        # 格式：MAC PORT VLAN（MAC 已被剔除）→ tokens 剩 [PORT, VLAN]
        # port 可能是數字（如 24）或 Trk1 等；VLAN 必為純數字
        if port_like:
            # 含字母的優先當 port（例如 Trk1）
            port = port_like[0]
            rest = [t for t in tokens if t != port]
            vlan = next((t for t in rest if _VLAN_RE.match(t)), None)
            return {'port': port, 'vlan': vlan}
        if len(numeric) >= 2:
            return {'port': numeric[0], 'vlan': numeric[-1]}
        if len(numeric) == 1:
            return {'port': numeric[0], 'vlan': None}
        return None

    # zyxel_os / 其他：先試 Cisco-style，不成再試 Aruba-style
    if port_like:
        port = port_like[-1]
        vlan = numeric[0] if numeric else None
        return {'port': port, 'vlan': vlan}
    if len(numeric) >= 2:
        return {'port': numeric[0], 'vlan': numeric[-1]}
    if numeric:
        return {'port': numeric[0], 'vlan': None}
    return None


def _is_same_mac(token: str, mac12: str) -> bool:
    try:
        return normalize_mac(token) == mac12
    except ValueError:
        return False


# ─── LLDP / CDP 鄰居解析 ───

_LABEL_SYSNAME = re.compile(
    r'^\s*(?:Neighbor\s+)?'
    r'(?:System[-\s]*Name|SystemName|Device\s*ID|Remote\s*System\s*Name|SysName)'
    r'\s*[:\-]\s*(.+?)\s*$', re.IGNORECASE)
_LABEL_MGMT = re.compile(
    r'^\s*(?:Neighbor\s+)?'
    r'(?:Management[-\s]*Address(?:\(es\))?|Mgmt\s*Addr(?:ess)?|IP\s*Address|'
    r'Management\s*IP)'
    r'\s*[:\-]\s*(.+?)\s*$', re.IGNORECASE)
_LABEL_PORT = re.compile(
    r'^\s*(?:Neighbor\s+)?'
    r'(?:Port[-\s]*ID|PortId|Remote\s*Port|Port\s*Description\s*\(remote\)|'
    r'Interface|PortDescr)'
    r'\s*[:\-]\s*(.+?)\s*$', re.IGNORECASE)


_ERROR_PATTERNS = (
    'invalid input',
    'unknown command',
    'ambiguous',
    'is not a physical interface',
    'not a valid',
    'module not present',
    'no lldp neighbor',
    'no neighbor',
)


def parse_neighbor(vendor: str, output: str) -> Optional[dict]:
    """解析 LLDP/CDP 輸出，回傳鄰居資訊。

    有效鄰居至少要有 `system_name` 或 `mgmt_ip`（光有 `remote_port`
    可能是 CLI 錯誤訊息誤匹配，視為無效）。
    """
    if not output or not output.strip():
        return None
    low = output.lower()
    for pat in _ERROR_PATTERNS:
        if pat in low:
            return None
    # Cisco CDP 輸出中的「Device ID」區塊與 LLDP 的「System Name」欄位共用同一解析流程。

    system_name: Optional[str] = None
    mgmt_ip: Optional[str] = None
    remote_port: Optional[str] = None

    for raw in output.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue

        if system_name is None:
            m = _LABEL_SYSNAME.match(line)
            if m:
                system_name = _clean_value(m.group(1))
                continue
        if mgmt_ip is None:
            m = _LABEL_MGMT.match(line)
            if m:
                # 可能是 "IP: 10.1.1.22" 或整行只有 IP
                val = m.group(1).strip()
                ip_m = _IP_RE.search(val)
                if ip_m:
                    mgmt_ip = ip_m.group(0)
                continue
        if remote_port is None:
            m = _LABEL_PORT.match(line)
            if m:
                remote_port = _clean_value(m.group(1))
                continue

    # Cisco CDP 特例：「Interface: Gi1/0/24,  Port ID (outgoing port): Gi1/0/1」
    # 上面的正則會抓到 "Gi1/0/24,"，需要改用 outgoing port 欄位
    m = re.search(
        r'Port\s*ID\s*\(outgoing\s*port\)\s*:\s*(\S+)',
        output, re.IGNORECASE)
    if m:
        remote_port = _clean_value(m.group(1))

    # CDP 「Management address(es)」或 Cisco LLDP「Management Addresses:」之後
    # IP 常於下一行以「IP address:」/「IP:」開頭（或獨立出現）
    if mgmt_ip is None:
        m = re.search(
            r'Management\s*addresses?(?:\(es\))?[^\n]*\n\s*'
            r'(?:IP(?:v4)?\s*(?:address)?\s*[:\-]\s*)?'
            r'((?:\d{1,3}\.){3}\d{1,3})',
            output, re.IGNORECASE)
        if m:
            mgmt_ip = m.group(1)

    # Aruba / 類似廠商：「Remote Management Address」區塊中，IP 另行
    # 出現為「Address : 10.1.1.22」（本身的 label 與 Management 無關）
    if mgmt_ip is None:
        m = re.search(
            r'Remote\s*Management\s*Address[^\n]*(?:\n[^\n]*){0,5}?'
            r'Address\s*[:\-]\s*((?:\d{1,3}\.){3}\d{1,3})',
            output, re.IGNORECASE)
        if m:
            mgmt_ip = m.group(1)

    # 沒有 system_name 也沒有 mgmt_ip → 不算有效鄰居（避免把錯誤訊息誤判）
    if not system_name and not mgmt_ip:
        return None
    return {
        'system_name': system_name,
        'mgmt_ip': mgmt_ip,
        'remote_port': remote_port,
    }


def _clean_value(v: str) -> str:
    v = v.strip().strip(',').strip()
    # 去掉常見尾巴（如 Cisco "Interface: Gi1/0/24,  Port ID..."）
    return v.split(',', 1)[0].strip()
