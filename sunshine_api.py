"""Small, loopback-only client for Sunshine's authenticated PIN pairing API."""
import base64
import json
import ssl
import urllib.error
import urllib.request


BASE_URL = 'https://127.0.0.1:47990'


def _request(path, username, password, method='GET', payload=None, timeout=35):
    if not username.strip() or not password:
        raise ValueError('Введи имя пользователя и пароль Sunshine.')
    # Sunshine normally uses a self-signed local certificate. Keep this client
    # pinned to loopback so credentials are never sent to a remote address.
    auth = base64.b64encode(f'{username.strip()}:{password}'.encode('utf-8')).decode('ascii')
    body = None if payload is None else json.dumps(payload).encode('utf-8')
    request = urllib.request.Request(
        BASE_URL + path, data=body, method=method,
        headers={'Authorization': 'Basic ' + auth,
                 'Accept': 'application/json',
                 **({'Content-Type': 'application/json'} if body is not None else {})})
    try:
        with urllib.request.urlopen(request, context=ssl._create_unverified_context(), timeout=timeout) as response:
            content_type = response.headers.get('Content-Type', '')
            if response.geturl().rstrip('/').endswith('/welcome') or 'application/json' not in content_type.lower():
                raise ValueError('Sunshine ещё не настроена. Один раз заверши её первоначальную настройку, затем PIN гостей можно будет подтверждать здесь.')
            result = json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError('Sunshine не приняла логин или пароль. Проверь данные учётной записи хоста.') from exc
        if exc.code == 404:
            raise ValueError('В этой версии Sunshine нет встроенного PIN-сопряжения через API. Обнови Sunshine.') from exc
        raise ValueError(f'Ошибка Sunshine API: HTTP {exc.code}.') from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ConnectionError('Не удалось подключиться к Sunshine на этом компьютере. Убедись, что Sunshine запущена.') from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Sunshine вернула неожиданный ответ. Проверь версию Sunshine.') from exc
    if not isinstance(result, dict):
        raise ValueError('Sunshine вернула неверный формат ответа.')
    return result


def pending_pairings(username, password):
    result = _request('/api/pin', username, password)
    if result.get('status') is False:
        raise ValueError('Sunshine отклонила запрос ожидающих подключений.')
    pairings = result.get('pairings')
    if not isinstance(pairings, list):
        raise ValueError('Sunshine не вернула список ожидающих гостей.')
    return [item for item in pairings if isinstance(item, dict) and item.get('id')]


def approve_pairing(username, password, pairing_id, pin, name):
    if not pairing_id:
        raise ValueError('Выбери ожидающего гостя из списка.')
    if len(pin) != 4 or not pin.isdigit():
        raise ValueError('PIN гостя должен состоять из четырёх цифр.')
    result = _request('/api/pin', username, password, method='POST', timeout=35,
                      payload={'pairing_id': pairing_id, 'pin': pin,
                               'name': name.strip()[:64] or 'PulsePlay'})
    return result.get('status') is True
