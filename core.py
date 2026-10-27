"""Validated Moonlight CLI integration. No transport proxy, shell or credentials."""
import base64
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


def make_invite(host, app='Desktop'):
    """Portable address card, not a password or access grant."""
    host = validate_host(host)
    app = app.strip()
    if not app or app.startswith('-') or len(app) > 128 or any(ord(c) < 32 for c in app):
        raise ValueError('Укажи название приложения Sunshine.')
    payload = json.dumps({'host': host, 'app': app}, ensure_ascii=False, separators=(',', ':'))
    return 'PP1:' + base64.urlsafe_b64encode(payload.encode('utf-8')).decode('ascii').rstrip('=')


def parse_invite(value):
    value = value.strip()
    if not value.startswith('PP1:') or len(value) > 1024:
        raise ValueError('Неверное приглашение PulsePlay.')
    token = value[4:]
    try:
        data = json.loads(base64.b64decode(
            token + '=' * (-len(token) % 4), altchars=b'-_', validate=True))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Приглашение повреждено.') from exc
    if not isinstance(data, dict) or not isinstance(data.get('host'), str) or not isinstance(data.get('app'), str):
        raise ValueError('Приглашение повреждено.')
    host = validate_host(data['host'])
    app = data['app'].strip()
    if not app or app.startswith('-') or len(app) > 128 or any(ord(c) < 32 for c in app):
        raise ValueError('Приглашение содержит неверное приложение.')
    return host, app

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

def _registered_executable(exe_name, product_name, service_name=None):
    """Find an installed Windows app from registry metadata; never scans the network."""
    if os.name != 'nt':
        return ''
    try:
        import winreg
    except ImportError:
        return ''

    def as_exe(value, require_expected_name=True):
        if not isinstance(value, str) or not value.strip():
            return ''
        value = os.path.expandvars(value.strip())
        match = re.match(r'^\s*"?(.+?\.exe)(?:"|\s|,|$)', value, re.IGNORECASE)
        if not match:
            return ''
        candidate = Path(match.group(1))
        if require_expected_name and candidate.name.casefold() != exe_name.casefold():
            return ''
        return str(candidate) if candidate.is_file() else ''

    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    views = (getattr(winreg, 'KEY_WOW64_64KEY', 0),
             getattr(winreg, 'KEY_WOW64_32KEY', 0), 0)
    for hive in hives:
        for view in views:
            key_path = rf'SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_name}'
            try:
                with winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | view) as key:
                    found = as_exe(winreg.QueryValueEx(key, '')[0])
                    if found:
                        return found
            except OSError:
                pass

            uninstall = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall'
            try:
                with winreg.OpenKey(hive, uninstall, 0, winreg.KEY_READ | view) as root:
                    subkeys = [winreg.EnumKey(root, i) for i in range(winreg.QueryInfoKey(root)[0])]
            except OSError:
                subkeys = []
            for subkey in subkeys:
                try:
                    with winreg.OpenKey(hive, uninstall + '\\' + subkey, 0,
                                        winreg.KEY_READ | view) as key:
                        display = str(winreg.QueryValueEx(key, 'DisplayName')[0])
                        if product_name.casefold() not in display.casefold():
                            continue
                        for value_name in ('DisplayIcon', 'InstallLocation'):
                            try:
                                raw = winreg.QueryValueEx(key, value_name)[0]
                            except OSError:
                                continue
                            found = as_exe(str(raw))
                            if found:
                                return found
                            location = Path(os.path.expandvars(str(raw).strip().strip('"')))
                            for candidate in (location / exe_name, location / 'bin' / exe_name):
                                if candidate.is_file():
                                    return str(candidate)
                except OSError:
                    pass

    if service_name:
        service_names = service_name if isinstance(service_name, (tuple, list)) else (service_name,)
        for name in service_names:
            for view in views:
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                        rf'SYSTEM\CurrentControlSet\Services\{name}',
                                        0, winreg.KEY_READ | view) as key:
                        service_exe = as_exe(winreg.QueryValueEx(key, 'ImagePath')[0],
                                             require_expected_name=False)
                        if service_exe:
                            service_path = Path(service_exe)
                            if service_path.name.casefold() == exe_name.casefold():
                                return str(service_path)
                            # Recent Sunshine installs run sunshinesvc.exe from tools/;
                            # the actual sunshine.exe lives one directory above.
                            for candidate in (service_path.parent / exe_name,
                                             service_path.parent.parent / exe_name):
                                if candidate.is_file():
                                    return str(candidate)
                except OSError:
                    pass
    return ''


def _find_program(exe_name, product_name, folders, command_names, service_name=None):
    for folder in folders:
        if folder:
            candidate = Path(folder) / exe_name
            if candidate.is_file():
                return str(candidate)
    for command in command_names:
        found = shutil.which(command)
        if found:
            return found
    return _registered_executable(exe_name, product_name, service_name)


def find_moonlight():
    """Locate Moonlight in common install folders, PATH, and Windows app records."""
    roots = (os.environ.get('ProgramFiles', ''), os.environ.get('ProgramW6432', ''),
             os.environ.get('ProgramFiles(x86)', ''), os.environ.get('LOCALAPPDATA', ''))
    folders = [str(Path(root) / relative) for root in roots if root for relative in
               ('Moonlight Game Streaming/Moonlight.exe', 'Moonlight/Moonlight.exe')]
    return _find_program('Moonlight.exe', 'moonlight', folders,
                         ('Moonlight.exe', 'moonlight'))


def find_sunshine():
    """Locate Sunshine locally, including the executable registered by its service."""
    roots = (os.environ.get('ProgramFiles', ''), os.environ.get('ProgramW6432', ''),
             os.environ.get('ProgramFiles(x86)', ''), os.environ.get('LOCALAPPDATA', ''))
    folders = [str(Path(root) / relative) for root in roots if root for relative in
               ('Sunshine/sunshine.exe', 'Programs/Sunshine/sunshine.exe')]
    return _find_program('sunshine.exe', 'sunshine', folders,
                         ('sunshine.exe', 'sunshine'),
                         service_name=('SunshineService', 'Sunshine'))

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
