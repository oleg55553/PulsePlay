"""Direct Sunshine/Moonlight diagnostics without a relay service."""
import ipaddress
import socket
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from core import validate_host

TCP_PORTS = (47984, 47989, 48010)
UDP_PORTS = (47998, 47999, 48000, 48002, 48010)
WAN_SERVICES = (
    'urn:schemas-upnp-org:service:WANIPConnection:1',
    'urn:schemas-upnp-org:service:WANPPPConnection:1',
    'urn:schemas-upnp-org:service:WANIPConnection:2',
)


def is_public_ipv4(value):
    try:
        address = ipaddress.ip_address(value)
        return address.version == 4 and address.is_global
    except ValueError:
        return False


def _router_url(location):
    """Allow HTTP requests only to a local IPv4 router."""
    parsed = urllib.parse.urlsplit(location)
    if parsed.scheme != 'http' or parsed.username or parsed.password or not parsed.hostname:
        raise ValueError('Недопустимый адрес роутера UPnP.')
    try:
        address = ipaddress.IPv4Address(parsed.hostname)
    except ipaddress.AddressValueError as exc:
        raise ValueError('Роутер UPnP должен сообщить локальный IPv4-адрес.') from exc
    if not address.is_private or address.is_loopback or address.is_link_local:
        raise ValueError('Ответ UPnP ведёт вне домашней сети.')
    return parsed


def _discover_router(timeout=2):
    request = ('M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n'
               'MAN: "ssdp:discover"\r\nMX: 1\r\n'
               'ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n\r\n')
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        sock.sendto(request.encode('ascii'), ('239.255.255.250', 1900))
        for _ in range(8):
            try:
                response, sender = sock.recvfrom(8192)
            except socket.timeout:
                break
            headers = response.decode('latin-1', errors='replace').split('\r\n')
            location = next((line.split(':', 1)[1].strip() for line in headers
                             if line.lower().startswith('location:')), '')
            if location:
                try:
                    if _router_url(location).hostname == sender[0]:
                        return location
                except ValueError:
                    continue
    raise ValueError('Роутер с UPnP не найден. Узнай WAN IP в панели роутера.')


def own_address():
    """Read the router WAN IPv4 using UPnP; no external IP lookup service."""
    location = _discover_router()
    parsed = _router_url(location)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(location, timeout=3) as response:
        if response.geturl() != location:
            raise ValueError('Роутер перенаправил запрос UPnP.')
        description = ET.fromstring(response.read(128 * 1024))
    service = control = None
    for item in description.iter():
        if item.tag.rsplit('}', 1)[-1] != 'service':
            continue
        fields = {child.tag.rsplit('}', 1)[-1]: (child.text or '').strip() for child in item}
        if fields.get('serviceType') in WAN_SERVICES:
            service, control = fields['serviceType'], fields.get('controlURL')
            break
    if not service or not control:
        raise ValueError('Роутер не поддерживает чтение внешнего IP через UPnP.')
    endpoint = urllib.parse.urljoin(location, control)
    if urllib.parse.urlsplit(endpoint).netloc != parsed.netloc:
        raise ValueError('Роутер сообщил посторонний адрес управления UPnP.')
    body = ('<?xml version="1.0"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">'
            '<s:Body><u:GetExternalIPAddress xmlns:u="' + service + '"/>'
            '</s:Body></s:Envelope>').encode('ascii')
    request = urllib.request.Request(endpoint, data=body, headers={
        'Content-Type': 'text/xml; charset="utf-8"',
        'SOAPAction': '"' + service + '#GetExternalIPAddress"',
    })
    with opener.open(request, timeout=3) as response:
        if response.geturl() != endpoint:
            raise ValueError('Роутер перенаправил запрос UPnP.')
        result = ET.fromstring(response.read(128 * 1024))
    address = next((node.text.strip() for node in result.iter()
                    if node.tag.rsplit('}', 1)[-1] == 'NewExternalIPAddress' and node.text), '')
    if not is_public_ipv4(address):
        raise ValueError('У роутера нет публичного IPv4 (возможен CGNAT или двойной NAT). '
                         'Попроси провайдера выдать публичный адрес.')
    return address


def diagnose(host):
    host = validate_host(host)
    lines = [f'Проверка доступности Sunshine по адресу {host}.']
    try:
        if not ipaddress.ip_address(host).is_global:
            lines.append('Этот IP не публичный. Он может работать внутри домашней сети '
                         'или VPN, если оба ПК подключены к одной сети.')
    except ValueError:
        pass
    for port in TCP_PORTS:
        try:
            with socket.create_connection((host, port), timeout=3):
                lines.append(f'TCP {port}: доступен.')
        except OSError as exc:
            lines.append(f'TCP {port}: недоступен ({str(exc)[:120]}).')
    lines.append('UDP ' + ', '.join(map(str, UDP_PORTS)) + ' этой проверкой не проверяется. '
                 'Доступность TCP не подтверждает видео, звук или ввод.')
    lines.append('Для прямого подключения проверяй с другой сети: локальная проверка '
                 'публичного IP может не работать без NAT loopback. Для VPN сначала '
                 'подключи оба ПК к одной виртуальной сети. Затем выполни сопряжение и запуск Moonlight.')
    return '\n'.join(lines)


def host_profile(keyboard=False, mouse=False, controller=False):
    values = {'keyboard': keyboard, 'mouse': mouse, 'controller': controller,
              'native_pen_touch': False}
    return ('# PulsePlay: apply locally in Sunshine Configuration > Input.\n'
            '# GLOBAL: applies to ALL clients after saving/restarting Sunshine.\n'
            '# Not per-user authorization. Does not restrict capture to a game.\n' +
            '\n'.join(f'{key} = {"enabled" if value else "disabled"}'
                      for key, value in values.items()) + '\n')
