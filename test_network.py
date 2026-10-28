import unittest
from unittest.mock import MagicMock, patch

from network import _radmin_ip_from_ipconfig, _router_url, diagnose, host_profile, is_public_ipv4, own_address


class NetworkTests(unittest.TestCase):
    def test_radmin_adapter_ip_is_detected_without_selecting_other_adapters(self):
        output = ('Windows IP Configuration\n\n'
                  'Ethernet adapter Radmin VPN:\n\n'
                  '   IPv4 Address. . . . . . . . . . . : 26.219.93.9\n'
                  '   Subnet Mask . . . . . . . . . . : 255.0.0.0\n\n'
                  'Ethernet adapter Ethernet:\n'
                  '   IPv4 Address. . . . . . . . . . . : 192.168.0.8\n')
        self.assertEqual(_radmin_ip_from_ipconfig(output), '26.219.93.9')

    def test_radmin_adapter_without_ipv4_is_not_detected(self):
        self.assertEqual(_radmin_ip_from_ipconfig('Ethernet adapter Radmin VPN:\n Media disconnected'), '')

    def test_public_address_classification(self):
        self.assertTrue(is_public_ipv4('8.8.8.8'))
        for value in ('100.64.1.2', '192.168.1.2', '127.0.0.1', '2001:db8::1', 'bad'):
            self.assertFalse(is_public_ipv4(value))

    def test_router_url_rejects_external_and_credentials(self):
        for value in ('https://192.168.1.1/desc.xml',
                      'http://8.8.8.8/desc.xml',
                      'http://user:pass@192.168.1.1/desc.xml',
                      'http://localhost/desc.xml'):
            with self.assertRaises(ValueError):
                _router_url(value)

    @patch('network.socket.create_connection')
    def test_direct_diagnosis_checks_sunshine_ports(self, connect):
        connect.return_value.__enter__ = MagicMock()
        result = diagnose('8.8.8.8')
        for port in (47984, 47989, 48010):
            connect.assert_any_call(('8.8.8.8', port), timeout=3)
        self.assertIn('UDP', result)
        self.assertIn('не проверяет', result)

    @patch('network.socket.create_connection', side_effect=OSError('unreachable'))
    def test_diagnosis_errors_and_private_address(self, connect):
        result = diagnose('100.64.1.2')
        self.assertIn('не публичный', result)
        self.assertIn('недоступен', result)

    @patch('network.socket.create_connection')
    def test_invalid_host_does_not_connect(self, connect):
        with self.assertRaises(ValueError):
            diagnose('--help')
        connect.assert_not_called()

    @patch('network._discover_router', return_value='http://192.168.1.1/desc.xml')
    @patch('network.urllib.request.build_opener')
    def test_own_address_from_router_only(self, build_opener, discover):
        description = (b'<root><service><serviceType>'
                       b'urn:schemas-upnp-org:service:WANIPConnection:1'
                       b'</serviceType><controlURL>/control</controlURL></service></root>')
        response = b'<r><NewExternalIPAddress>8.8.8.8</NewExternalIPAddress></r>'
        contexts = []
        for url, payload in [('http://192.168.1.1/desc.xml', description),
                             ('http://192.168.1.1/control', response)]:
            value = MagicMock()
            value.geturl.return_value = url
            value.read.return_value = payload
            context = MagicMock()
            context.__enter__.return_value = value
            contexts.append(context)
        build_opener.return_value.open.side_effect = contexts
        self.assertEqual(own_address(), '8.8.8.8')
        self.assertEqual(build_opener.return_value.open.call_count, 2)

    @patch('network._discover_router', return_value='http://192.168.1.1/desc.xml')
    @patch('network.urllib.request.build_opener')
    def test_cgnat_address_rejected(self, build_opener, discover):
        description = (b'<root><service><serviceType>'
                       b'urn:schemas-upnp-org:service:WANIPConnection:1'
                       b'</serviceType><controlURL>/control</controlURL></service></root>')
        response = b'<r><NewExternalIPAddress>100.64.1.2</NewExternalIPAddress></r>'
        contexts = []
        for url, payload in [('http://192.168.1.1/desc.xml', description),
                             ('http://192.168.1.1/control', response)]:
            value = MagicMock()
            value.geturl.return_value = url
            value.read.return_value = payload
            context = MagicMock()
            context.__enter__.return_value = value
            contexts.append(context)
        build_opener.return_value.open.side_effect = contexts
        with self.assertRaisesRegex(ValueError, 'CGNAT'):
            own_address()

    def test_host_profile_remains_read_only(self):
        profile = host_profile()
        self.assertIn('keyboard = disabled', profile)
        self.assertIn('GLOBAL', profile)
        self.assertIn('controller = enabled', host_profile(controller=True))


if __name__ == '__main__':
    unittest.main()
