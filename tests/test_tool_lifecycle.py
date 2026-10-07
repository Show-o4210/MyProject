"""Rendered routes prove that retirement notices stay outside client app state."""
from pathlib import Path
import unittest

from flask import Flask

from blueprints.home import home_bp
from blueprints.unity import unity_bp
from blueprints.phantom import phantom_bp
from blueprints.deck_editor import deck_editor_bp
from blueprints.level_editor import level_editor_bp
from blueprints.downloads import downloads_bp

ROOT = Path(__file__).resolve().parents[1]


class ToolLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
        self.app.testing = True
        for blueprint in (home_bp, unity_bp, phantom_bp, deck_editor_bp, level_editor_bp, downloads_bp):
            self.app.register_blueprint(blueprint)
        self.client = self.app.test_client()

    def test_notices_are_visible_and_cannot_be_dismissed(self):
        for route in ('/', '/deck-editor', '/editor', '/downloads', '/phantom'):
            with self.subTest(route=route):
                html = self.client.get(route).get_data(as_text=True)
                notice = html.split('<aside id="tool-lifecycle-notice"', 1)[1].split('</aside>', 1)[0]
                self.assertIn('可能会关闭', notice)
                self.assertIn('如果你正在使用，请与我联系', notice)
                self.assertIn('https://qm.qq.com/q/PayU4f00iQ', notice)
                for marker in ('<button', '<details', 'v-if', 'v-show', 'onclick', 'localStorage'):
                    self.assertNotIn(marker, notice)
                self.assertLess(html.index('id="tool-lifecycle-notice"'), html.index('<main'))
        self.assertNotIn('id="tool-lifecycle-notice"', self.client.get('/unity').get_data(as_text=True))

    def test_phantom_is_retired_and_removed_from_discovery(self):
        response = self.client.get('/phantom')
        self.assertEqual(response.status_code, 410)
        html = response.get_data(as_text=True)
        self.assertIn('幻影引擎已归档', html)
        self.assertIn('noindex, follow', html)
        self.assertNotIn('js/phantom/main.js', html)
        for route in ('/api/phantom/ping', '/api/phantom/config'):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 410)
            self.assertTrue(response.json['archived'])
        self.assertNotIn('href="/phantom"', self.client.get('/').get_data(as_text=True))
        self.assertNotIn('/phantom', self.client.get('/sitemap.xml').get_data(as_text=True))
        self.assertNotIn('/phantom', (ROOT / 'static' / 'sitemap.xml').read_text())
        for path in ('js/phantom/main.js', 'css/phantom.css', 'data/phantom_config.json'):
            self.assertEqual(self.client.get('/static/' + path).status_code, 404)
