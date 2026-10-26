import unittest
from unittest.mock import patch, MagicMock
from network import diagnose, host_profile, route_kind, own_address

class NetworkTests(unittest.TestCase):
    def test_direct_after_relay(self):
        self.assertEqual(route_kind('pong via DERP(fra) in 80ms\npong via 1.2.3.4:4321 in 12ms'), 'direct')

    def test_relay_and_unknown(self):
        self.assertEqual(route_kind('pong via DERP(fra) in 80ms'), 'relay')
        self.assertEqual(route_kind('no direct connection'), 'unknown')
        self.assertEqual(route_kind('pong via [2001:db8::1]:456 in 20ms'), 'direct')

    def test_read_only_default(self):
        p = host_profile()
        for key in ('keyboard','mouse','controller','native_pen_touch'):
            self.assertIn(key+' = disabled', p)
        self.assertIn('GLOBAL', p)

    def test_gamepad_only(self):
        p = host_profile(controller=True)
        self.assertIn('controller = enabled', p)
        self.assertIn('keyboard = disabled', p)
        self.assertIn('mouse = disabled', p)

    @patch('network.socket.create_connection')
    @patch('network.find_tailscale', return_value=None)
    def test_missing_dependency(self, find, connect):
        connect.return_value = MagicMock()
        result = diagnose('100.64.1.2')
        self.assertIn('Tailscale не найден', result)
        self.assertIn('НЕ проверка видеопотока', result)
        connect.assert_called_once_with(('100.64.1.2', 47989), timeout=4)

    @patch('network.socket.create_connection', side_effect=OSError('unreachable'))
    @patch('network.run_cli', return_value='not JSON')
    @patch('network.find_tailscale', return_value='tailscale')
    def test_diagnostic_errors(self, find, run, connect):
        result = diagnose('100.64.1.2')
        self.assertIn('Ошибка диагностики', result)
        self.assertIn('недоступен', result)

    @patch('network.find_tailscale')
    def test_no_command_for_invalid_host(self, find):
        with self.assertRaises(ValueError):
            diagnose('--help')
        find.assert_not_called()

class OwnAddressTests(unittest.TestCase):
    @patch('network.run_cli', return_value='{"BackendState":"Running","TailscaleIPs":["fd7a:115c:a1e0::1","100.80.1.2"]}')
    @patch('network.find_tailscale', return_value='tailscale')
    def test_own_ipv4_preferred(self, find, run):
        self.assertEqual(own_address(), '100.80.1.2')
        run.assert_called_once_with('tailscale', ['status', '--json'])

    @patch('network.run_cli', return_value='{"BackendState":"Stopped","TailscaleIPs":["100.80.1.2"]}')
    @patch('network.find_tailscale', return_value='tailscale')
    def test_stopped_does_not_show_old_ip(self, find, run):
        with self.assertRaises(ValueError):
            own_address()

    @patch('network.run_cli', return_value='{"BackendState":"Running","TailscaleIPs":["192.168.1.2","bad"],"Peer":{"ip":"100.80.1.3"}}')
    @patch('network.find_tailscale', return_value='tailscale')
    def test_no_lan_or_peer_fallback(self, find, run):
        with self.assertRaises(ValueError):
            own_address()

    @patch('network.find_tailscale', return_value=None)
    def test_missing(self, find):
        with self.assertRaisesRegex(ValueError, 'Установи'):
            own_address()

if __name__ == '__main__':
    unittest.main()
