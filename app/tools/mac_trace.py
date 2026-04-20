"""MAC 追蹤引擎。

公開函式 `run_mac_trace(run_id)`：
1. 讀取 ToolRun、解析 query（mac / start_device_id / max_hops）
2. 從指定的起點 switch 開始
3. 依 `mac address-table` 找到 port，再以 LLDP/CDP 查該 port 的鄰居
4. 若鄰居是 DB 裡的另一台可存取 switch → 跳下一台；否則視為 edge port
5. 結果寫回 ToolRun.result（JSON），更新 status/finished_at

本模組不直接依賴 Flask request context，可在背景 thread 中以 app.app_context() 呼叫。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from app import db
from app.crypto import safe_decrypt
from app.models import Device, ToolRun, User
from app.settings_store import get_netmiko_timeout
from app.tools.mac_utils import normalize_mac
from app.tools.vendors import (build_lag_members_cmds, build_mac_lookup_cmds,
                               build_neighbor_cmds, build_port_desc_cmds,
                               is_lag_port, parse_lag_members, parse_mac_row,
                               parse_neighbor, parse_port_desc)

SUPPORTED_VENDORS = ('cisco_ios', 'aruba_os', 'zyxel_os')
_PAGING_BY_VENDOR = {
    'cisco_ios': 'terminal length 0',
    'aruba_os':  'no page',
    'zyxel_os':  'terminal length 0',
}


# ─── 公開入口 ───

def run_mac_trace(run_id: int) -> None:
    run = db.session.get(ToolRun, run_id)
    if run is None:
        return

    try:
        query = json.loads(run.query_json or '{}')
        mac_raw = query.get('mac') or ''
        start_device_id = query.get('start_device_id')
        max_hops = int(query.get('max_hops') or 10)
        user_id = run.user_id

        try:
            mac12 = normalize_mac(mac_raw)
        except ValueError as e:
            _finalize(run, status='failed', error=str(e), result={'hops': []})
            return

        accessible_ids = _accessible_device_ids(user_id)
        if not accessible_ids:
            _finalize(run, status='failed',
                      error='沒有可存取的 switch（vendor 須為 cisco_ios / aruba_os / zyxel_os）',
                      result={'hops': []})
            return

        # Step 1: 定位起點
        if not start_device_id:
            _finalize(run, status='failed',
                      error='請指定起點 switch',
                      result={'hops': []})
            return
        if int(start_device_id) not in accessible_ids:
            _finalize(run, status='failed',
                      error='指定的起點設備不存在或無權存取',
                      result={'hops': []})
            return
        start = db.session.get(Device, int(start_device_id))
        first_probe = _probe_mac(start, mac12)
        if first_probe is None:
            _finalize(run, status='not_found',
                      error=None,
                      result={'hops': [],
                              'message': f'{start.name} 的 MAC table 未找到該 MAC'})
            return

        # Step 2: hop loop
        hops: list[dict] = []
        visited: set[int] = set()
        current = start
        current_probe = first_probe  # {'mac_row': {...}, 'neighbor_raw': str}

        for seq in range(1, max_hops + 1):
            if current.id in visited:
                if hops:
                    hops[-1]['note'] = 'loop detected（已走過此 switch，停止）'
                break
            visited.add(current.id)

            if current_probe is None:
                current_probe = _probe_mac(current, mac12)
            if current_probe is None:
                hops.append({
                    'seq': seq,
                    'device_id': current.id,
                    'device_name': current.name,
                    'vendor': current.vendor,
                    'port': None,
                    'vlan': None,
                    'neighbor': None,
                    'note': 'MAC 未在此 switch 學到',
                })
                break

            mac_row = current_probe['mac_row']
            neighbor_raw = current_probe.get('neighbor_raw')
            neighbor = (parse_neighbor(current.vendor, neighbor_raw)
                        if neighbor_raw else None)

            hops.append({
                'seq': seq,
                'device_id': current.id,
                'device_name': current.name,
                'vendor': current.vendor,
                'port': mac_row.get('port'),
                'port_desc': current_probe.get('port_desc'),
                'vlan': mac_row.get('vlan'),
                'lag_members': current_probe.get('lag_members') or [],
                'neighbor_via': current_probe.get('neighbor_via'),
                'neighbor': neighbor,
                'note': None,
            })

            next_dev = _find_device_by_neighbor(neighbor, accessible_ids,
                                                exclude_ids=visited)
            if next_dev is None:
                break
            current = next_dev
            current_probe = None  # 下一輪再查

        if len(hops) >= max_hops and hops and hops[-1].get('neighbor'):
            hops[-1]['note'] = (hops[-1].get('note') or '') + \
                f' 已達最大 hop 數 {max_hops}'

        status = 'success' if hops else 'not_found'
        _finalize(run, status=status, error=None,
                  result={'hops': hops, 'message': _summarize(hops)})

    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        _finalize(run, status='failed', error=f'執行失敗：{e}',
                  result={'hops': []})


# ─── 資料輔助 ───

def _accessible_device_ids(user_id: int) -> set[int]:
    user = db.session.get(User, user_id)
    if user is None:
        return set()
    q = Device.query.filter(Device.is_active.is_(True),
                            Device.vendor.in_(SUPPORTED_VENDORS))
    if user.is_admin:
        return {d.id for d in q.all()}
    gids = user.group_ids or []
    if not gids:
        return set()
    return {d.id for d in q.filter(Device.group_id.in_(gids)).all()}


def _find_device_by_neighbor(neighbor: Optional[dict],
                             accessible_ids: set[int],
                             exclude_ids: set[int]) -> Optional[Device]:
    if not neighbor:
        return None
    candidates = (Device.query
                  .filter(Device.id.in_(accessible_ids - exclude_ids))
                  .all())
    ip = (neighbor.get('mgmt_ip') or '').strip()
    name = (neighbor.get('system_name') or '').strip().lower()

    if ip:
        for d in candidates:
            if d.ip_address.strip() == ip:
                return d
    if name:
        # 去除 FQDN 後綴
        base = name.split('.', 1)[0]
        for d in candidates:
            if d.name.strip().lower() == name or d.name.strip().lower() == base:
                return d
    return None


# ─── SSH 查詢 ───

def _probe_mac(device: Device, mac12: str) -> Optional[dict]:
    """查單一 switch：先 MAC lookup，有命中再查鄰居。

    回傳 {'mac_row': {...}, 'neighbor_raw': str|None} 或 None（未命中）。
    失敗 / 連線錯誤回傳 None（視為未命中，不中斷其他並行搜尋）。
    """
    from netmiko import ConnectHandler

    mac_cmds = build_mac_lookup_cmds(device.vendor, mac12)
    if not mac_cmds:
        return None
    if device.credential is None:
        return None

    cred = device.credential
    password = safe_decrypt(cred.password_enc)
    enable_pw = safe_decrypt(cred.enable_password_enc or '')
    timeout = get_netmiko_timeout()

    params = {
        'device_type': device.vendor,
        'host':        device.ip_address,
        'port':        device.port,
        'username':    cred.username,
        'password':    password,
        'conn_timeout': timeout,
        'timeout':     timeout,
        'fast_cli':    False,
    }
    if enable_pw:
        params['secret'] = enable_pw

    try:
        with ConnectHandler(**params) as conn:
            if enable_pw:
                try:
                    conn.enable()
                except Exception:
                    pass
            paging = _PAGING_BY_VENDOR.get(device.vendor)
            if paging:
                try:
                    conn.send_command_timing(paging, read_timeout=10,
                                             strip_prompt=False,
                                             strip_command=False)
                except Exception:
                    pass

            mac_row = None
            for mac_cmd in mac_cmds:
                mac_out = _safe_send(conn, mac_cmd, timeout)
                if not mac_out:
                    continue
                # 指令不支援時多半是 "Invalid input" / "Unknown command"
                low = mac_out.lower()
                if ('invalid input' in low or 'unknown command' in low
                        or 'ambiguous' in low):
                    continue
                mac_row = parse_mac_row(device.vendor, mac_out, mac12)
                if mac_row:
                    break
            if not mac_row:
                return None

            # LAG 展開：若 MAC 學到 lag / port-channel，實體成員 port 才有 LLDP 鄰居
            probe_ports = [mac_row['port']]
            lag_members: list[str] = []
            if is_lag_port(device.vendor, mac_row['port']):
                for lag_cmd in build_lag_members_cmds(
                        device.vendor, mac_row['port']):
                    lag_out = _safe_send(conn, lag_cmd, timeout)
                    if not lag_out:
                        continue
                    low = lag_out.lower()
                    if ('invalid input' in low or 'unknown command' in low):
                        continue
                    members = parse_lag_members(
                        device.vendor, lag_out, mac_row['port'])
                    if members:
                        lag_members = members
                        # 先試 LAG 介面本身（有些機型支援），再試實體成員
                        probe_ports = [mac_row['port']] + members
                        break

            neighbor_raw = None
            neighbor_via: Optional[str] = None
            for probe_port in probe_ports:
                found_for_port = False
                for nbr_cmd in build_neighbor_cmds(device.vendor, probe_port):
                    out = _safe_send(conn, nbr_cmd, timeout)
                    if not out or not out.strip():
                        continue
                    parsed = parse_neighbor(device.vendor, out)
                    if parsed:
                        neighbor_raw = out
                        if probe_port != mac_row['port']:
                            neighbor_via = probe_port
                        found_for_port = True
                        break
                    # 即使解析失敗，保留 raw 方便除錯
                    if neighbor_raw is None:
                        neighbor_raw = out
                if found_for_port:
                    break
            # 取得 interface description
            port_desc: Optional[str] = None
            for desc_cmd in build_port_desc_cmds(
                    device.vendor, mac_row['port']):
                desc_out = _safe_send(conn, desc_cmd, timeout)
                if not desc_out:
                    continue
                port_desc = parse_port_desc(
                    device.vendor, desc_out, mac_row['port'])
                if port_desc:
                    break

            return {
                'mac_row': mac_row,
                'neighbor_raw': neighbor_raw,
                'lag_members': lag_members,
                'neighbor_via': neighbor_via,
                'port_desc': port_desc,
            }
    except Exception:
        return None


def _safe_send(conn, cmd: str, timeout: int) -> str:
    try:
        return conn.send_command(cmd, read_timeout=timeout)
    except Exception:
        try:
            return conn.send_command_timing(cmd, read_timeout=timeout,
                                            last_read=2.0)
        except Exception:
            return ''


# ─── 寫回結果 ───

def _finalize(run: ToolRun, *, status: str, error: Optional[str],
              result: dict) -> None:
    run.status = status
    run.error_message = error
    run.result_json = json.dumps(result, ensure_ascii=False)
    run.finished_at = datetime.now(timezone.utc)
    db.session.commit()


def _summarize(hops: list[dict]) -> str:
    if not hops:
        return ''
    last = hops[-1]
    total = len(hops)
    port = last.get('port') or '?'
    vlan = last.get('vlan')
    tail = f'{last["device_name"]} {port}'
    if vlan:
        tail += f' (VLAN {vlan})'
    return f'{total} 跳，終點：{tail}'
