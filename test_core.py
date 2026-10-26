import tempfile
from pathlib import Path
import unittest
from core import load_settings, save_settings, stream_args, validate_host, make_invite, parse_invite

class CoreTests(unittest.TestCase):
    def test_invitation_roundtrip(self):
        invite = make_invite('8.8.8.8', 'Игра & друзья')
        self.assertEqual(parse_invite(invite), ('8.8.8.8', 'Игра & друзья'))
        self.assertNotIn('8.8.8.8', invite)

    def test_invalid_invitation(self):
        for value in ('', 'PP1:!!', 'PP1:W10', 'https://example.com'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_invite(value)

    def args(self, **changes):
        params=dict(host='192.168.1.10', app='My Game', resolution='1920x1080',fps='120',bitrate='35',codec='auto',low_latency=True,overlay=True)
        params.update(changes)
        return stream_args(**params)

    def test_network_addresses(self):
        for host in ['192.168.1.4','100.64.1.4','gaming-pc','pc.example.org','::1']:
            self.assertEqual(validate_host(host),host)

    def test_invalid_addresses(self):
        for host in ['', '--help','host;calc','https://host','host:123','a b','host\narg','-host']:
            with self.subTest(host=host), self.assertRaises(ValueError):
                validate_host(host)

    def test_units_and_latency(self):
        args=self.args()
        self.assertEqual(args[args.index('--bitrate')+1],'35000')
        self.assertEqual(args[args.index('--fps')+1],'120')
        self.assertIn('--no-vsync',args)
        self.assertIn('--no-frame-pacing',args)
        self.assertIn('--no-quit-after',args)
        self.assertEqual(args[2],'My Game')
        self.assertEqual(args[args.index('--video-decoder')+1],'hardware')

    def test_display_mode(self):
        for full, expected in [(True, 'fullscreen'), (False, 'windowed')]:
            args = self.args(fullscreen=full)
            self.assertEqual(args[args.index('--display-mode')+1], expected)
        args = self.args()
        self.assertEqual(args[args.index('--display-mode')+1], 'fullscreen')

    def test_smooth_mode(self):
        args=self.args(low_latency=False,overlay=False)
        self.assertIn('--vsync',args)
        self.assertIn('--frame-pacing',args)
        self.assertIn('--no-performance-overlay',args)
        self.assertNotIn('--no-vsync',args)

    def test_invalid_values(self):
        for changes in [dict(fps='500'),dict(fps='abc'),dict(bitrate='0'),dict(bitrate='151'),dict(codec='bad'),dict(app='--help'),dict(app=''),dict(resolution='bad')]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.args(**changes)

    def test_app_stays_one_argument(self):
        self.assertEqual(self.args(app='Game & Friends')[2],'Game & Friends')

    def test_settings_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'nested'/'settings.json'
            self.assertEqual(load_settings(path),{})
            save_settings({'app':'Игра'},path)
            self.assertEqual(load_settings(path),{'app':'Игра'})
            path.write_text('{bad')
            self.assertEqual(load_settings(path),{})
            path.write_text('[]')
            self.assertEqual(load_settings(path),{})

if __name__=='__main__':
    unittest.main()
