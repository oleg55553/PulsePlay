import unittest
from unittest.mock import MagicMock, patch

from sunshine_api import approve_pairing, pending_pairings


class SunshineApiTests(unittest.TestCase):
    @patch('sunshine_api._request', return_value={'pairings': [
        {'id': 'pair-1', 'name': 'Guest', 'address': '192.0.2.4'}]})
    def test_lists_pending_guest_requests(self, request):
        result = pending_pairings('admin', 'secret')
        self.assertEqual(result[0]['id'], 'pair-1')
        request.assert_called_once_with('/api/pin', 'admin', 'secret')

    @patch('sunshine_api._request', return_value={'status': True})
    def test_approves_selected_guest_with_pin(self, request):
        self.assertTrue(approve_pairing('admin', 'secret', 'pair-1', '0042', 'Guest PC'))
        request.assert_called_once_with(
            '/api/pin', 'admin', 'secret', method='POST', timeout=35,
            payload={'pairing_id': 'pair-1', 'pin': '0042', 'name': 'Guest PC'})

    @patch('sunshine_api._request')
    def test_rejects_invalid_pin_before_calling_sunshine(self, request):
        with self.assertRaisesRegex(ValueError, 'четырёх цифр'):
            approve_pairing('admin', 'secret', 'pair-1', '42', 'Guest PC')
        request.assert_not_called()

    @patch('sunshine_api.urllib.request.urlopen')
    def test_explains_first_time_sunshine_setup_instead_of_opening_site(self, urlopen):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = 'https://127.0.0.1:47990/welcome'
        response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        urlopen.return_value = response
        with self.assertRaisesRegex(ValueError, 'первоначальную настройку'):
            pending_pairings('admin', 'secret')


if __name__ == '__main__':
    unittest.main()
