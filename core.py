"""Validated Moonlight CLI integration. No transport proxy, shell or credentials."""
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil

PRESETS = {
    'Быстрый • 720p / 60': ('1280x720', 60, 10),
    'Баланс • 1080p / 60': ('1920x1080', 60, 20),
    'Плавный • 1080p / 120': ('1920x1080', 120, 35),
    'Чёткий • 1440p / 120': ('2560x1440', 120, 50),
}

def validate_host(value):
    value = value.strip()
    if not value or len(value) > 253:
        raise ValueError('Укажите IP или имя игрового компьютера.')
    try:
        ipaddress.ip_address(value)
        return value
    except ValueError:
        pass
    if not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', x)
               for x in value.split('.')):
        raise ValueError('Нужен IP или DNS-адрес без http://, порта и пробелов.')
    return value

def stream_args(host, app, resolution, fps, bitrate, codec, low_latency, overlay, fullscreen=True):
    host = validate_host(host)
    app = app.strip()
    if not app or app.startswith('-') or len(app) > 128 or any(ord(c) < 32 for c in app):
        raise ValueError('Укажите название приложения из Sunshine, например Desktop.')
    if resolution not in ('1280x720', '1920x1080', '2560x1440', '3840x2160'):
        raise ValueError('Неизвестное разрешение.')
    if int(fps) not in (30, 60, 90, 120, 144, 165, 240):
        raise ValueError('Выберите FPS из списка.')
    if not 5 <= int(bitrate) <= 150:
        raise ValueError('Битрейт должен быть от 5 до 150 Мбит/с.')
    if codec not in ('auto', 'H.264', 'HEVC', 'AV1'):
        raise ValueError('Неизвестный кодек.')
    args = ['stream', host, app, '--resolution', resolution, '--fps', str(fps),
            '--bitrate', str(int(bitrate) * 1000), '--video-codec', codec,
            '--video-decoder', 'hardware', '--display-mode', 'fullscreen' if fullscreen else 'windowed',
            '--no-quit-after', '--no-hdr', '--no-absolute-mouse', '--multi-controller',
            '--performance-overlay' if overlay else '--no-performance-overlay']
    args += ['--no-vsync', '--no-frame-pacing'] if low_latency else ['--vsync', '--frame-pacing']
    return args

def find_moonlight():
    for base in (os.environ.get('ProgramFiles', ''), os.environ.get('ProgramFiles(x86)', '')):
        if base:
            candidate = Path(base) / 'Moonlight Game Streaming' / 'Moonlight.exe'
            if candidate.is_file():
                return str(candidate)
    return shutil.which('Moonlight.exe') or shutil.which('moonlight') or ''

def config_path():
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.config'))) / 'PulsePlay' / 'settings.json'

def load_settings(path=None):
    try:
        value = json.loads((path or config_path()).read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}

def save_settings(value, path=None):
    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)
