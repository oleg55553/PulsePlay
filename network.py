"""Read-only diagnostics for an explicitly supplied game host."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from core import validate_host

def find_tailscale():
    base = os.environ.get('ProgramFiles', '')
    path = Path(base) / 'Tailscale' / 'tailscale.exe'
    return str(path) if base and path.is_file() else shutil.which('tailscale')

def route_kind(output):
    lines = output.splitlines()
    # A direct response must include the endpoint, not merely the word "direct".
    for line in reversed(lines):
        if re.search(r'via (?:\d{1,3}\.){3}\d{1,3}:\d+ in ', line) or re.search(r'via \[[0-9a-fA-F:]+\]:\d+ in ', line):
            return 'direct'
        if re.search(r'via (?:DERP\(|peer-relay)', line):
            return 'relay'
    return 'unknown'

def run_cli(exe, args, timeout=15):
    result = subprocess.run([exe, *args], capture_output=True, text=True,
        encoding='utf-8', errors='replace', timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError((result.stderr or result.stdout or 'Ошибка Tailscale').strip()[:1500])
    return result.stdout

def diagnose(host):
    host = validate_host(host)
    lines = [f'Проверка адреса: {host}']
    exe = find_tailscale()
    if not exe:
        lines.append('Tailscale не найден. Установи его на обоих устройствах и войди в аккаунт.')
    else:
        try:
            data = json.loads(run_cli(exe, ['status', '--json']))
            lines.append('Tailscale: ' + str(data.get('BackendState', 'неизвестно')))
            lines.append('Адреса этого устройства: ' + ', '.join(data.get('TailscaleIPs', [])))
            if data.get('BackendState') == 'Running':
                try:
                    output = run_cli(exe, ['ping', host], timeout=20)
                    kind = route_kind(output)
                    lines.append({'direct':'Маршрут: прямой — подходит для теста игры.',
                        'relay':'Маршрут: ретранслятор — низкая задержка не подтверждена.',
                        'unknown':'Маршрут не определён; смотри вывод ниже.'}[kind])
                    lines.append(output.strip()[:2500])
                except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                    lines.append('Проверка маршрута не завершена: ' + str(exc)[:500])
        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
            lines.append('Ошибка диагностики Tailscale: ' + str(exc)[:500])
    try:
        with socket.create_connection((host, 47989), timeout=4):
            lines.append('TCP 47989 доступен. Это НЕ проверка видеопотока, UDP или прав доступа.')
    except OSError as exc:
        lines.append('TCP 47989 недоступен: ' + str(exc)[:250])
    lines.append('Значения ping — сетевая задержка, не полная задержка управления.\n'
                 'Далее: сопряжение → игра → статистика Moonlight. Нестандартные порты здесь не проверяются.')
    return '\n'.join(lines)

def host_profile(keyboard=False, mouse=False, controller=False):
    values = {'keyboard':keyboard, 'mouse':mouse, 'controller':controller,
              'native_pen_touch':False}
    return ('# PulsePlay: apply locally in Sunshine Configuration > Input.\n'
            '# GLOBAL: applies to ALL clients after saving/restarting Sunshine.\n'
            '# Not per-user authorization. Does not restrict capture to a game.\n' +
            '\n'.join(f'{key} = {"enabled" if value else "disabled"}' for key,value in values.items()) + '\n')


def own_address():
    """Return a validated local Tailscale address, never a peer/public/LAN fallback."""
    exe = find_tailscale()
    if not exe:
        raise ValueError('Установи Tailscale на этот компьютер.')
    data = json.loads(run_cli(exe, ['status', '--json']))
    if not isinstance(data, dict):
        raise ValueError('Не удалось прочитать состояние Tailscale.')
    state = data.get('BackendState')
    if state != 'Running':
        raise ValueError('Открой Tailscale и подключись к аккаунту. Состояние: ' + str(state or 'неизвестно'))
    raw = data.get('TailscaleIPs', [])
    addresses = []
    for value in raw if isinstance(raw, list) else []:
        try:
            addresses.append(ipaddress.ip_address(value))
        except (ValueError, TypeError):
            continue
    addresses = [a for a in addresses if a in (ipaddress.ip_network('100.64.0.0/10') if a.version == 4 else ipaddress.ip_network('fd7a:115c:a1e0::/48'))]
    if not addresses:
        raise ValueError('Tailscale подключён, но IP ещё не получен. Нажми «Обновить».')
    addresses.sort(key=lambda a: a.version)
    return str(addresses[0])
