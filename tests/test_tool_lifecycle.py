"""Retired URLs must not load the old editors or mutate browser storage."""
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
from flask import Flask
from blueprints.home import home_bp
from blueprints.unity import unity_bp
from blueprints.phantom import phantom_bp
from blueprints.deck_editor import deck_editor_bp
from blueprints.level_editor import level_editor_bp
from blueprints.downloads import downloads_bp

ROOT = Path(__file__).resolve().parents[1]
PAGES = {'/editor': '关卡编辑器', '/deck-editor': '卡组编辑器', '/phantom': '幻影引擎'}
APIS = [('/api/init_data', 'GET'), ('/api/quick_export', 'POST'),
        ('/api/editor/init-data', 'GET'), ('/api/editor/ab/list', 'GET'),
        ('/api/editor/ab/extract', 'POST'), ('/api/editor/ab/pack', 'POST'),
        ('/api/phantom/ping', 'GET'), ('/api/phantom/config', 'GET')]


class ToolLifecycleTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__, template_folder=str(ROOT / 'templates'), static_folder=str(ROOT / 'static'))
        app.testing = True
        for blueprint in (home_bp, unity_bp, phantom_bp, deck_editor_bp, level_editor_bp, downloads_bp):
            app.register_blueprint(blueprint)
        self.client = app.test_client()

    def test_retired_pages_are_410_without_editor_scripts_or_storage_changes(self):
        for route, label in PAGES.items():
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 410)
                html = response.get_data(as_text=True)
                self.assertIn(label + '已归档', html)
                self.assertIn('noindex, follow', html)
                self.assertIn('href="/unity"', html)
                for marker in ('localStorage', 'createApp', 'vue-3.5.13', 'QQ', 'qm.qq.com', '可能会关闭'):
                    self.assertNotIn(marker, html)

    def test_retired_apis_never_start_unity_even_with_invalid_input(self):
        with patch('utils.unity_jobs.run_unity_job', side_effect=AssertionError('retired tool ran')):
            for route, method in APIS:
                with self.subTest(route=route):
                    response = self.client.open(route, method=method, data=b'not JSON', content_type='application/json')
                    self.assertEqual(response.status_code, 410)
                    self.assertTrue(response.json['archived'])

    def test_closed_tools_removed_from_discovery_and_old_notice_removed(self):
        home = self.client.get('/').get_data(as_text=True)
        live_map = self.client.get('/sitemap.xml').get_data(as_text=True)
        static_map = (ROOT / 'static/sitemap.xml').read_text(encoding='utf-8')
        for route in PAGES:
            self.assertNotIn(f'href="{route}"', home)
            self.assertNotIn(route, live_map)
            self.assertNotIn(route, static_map)
        for route in ('/', '/unity', '/downloads'):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertNotIn('id="tool-lifecycle-notice"', html)
            self.assertNotIn('qm.qq.com', html)

    def test_archived_sources_are_not_public_static_assets(self):
        for path in ('js/json_budget.js', 'js/json_worker.js', 'js/phantom/main.js', 'css/phantom.css', 'data/phantom_config.json'):
            self.assertEqual(self.client.get('/static/' + path).status_code, 404)
        self.assertEqual(self.client.get('/archive/editors/templates/level_editor.html').status_code, 404)

    def test_download_page_has_one_direct_cloud_link_without_dialog_or_vue(self):
        html = self.client.get('/downloads').get_data(as_text=True)
        self.assertEqual(html.count('href="https://pan.quark.cn/s/92d058b77b5f"'), 1)
        for marker in ('download-dialog', 'data-download-name', 'QQ', 'qm.qq.com', 'vue-3.5.13'):
            self.assertNotIn(marker, html)
        self.assertIn('打开夸克网盘</a>', html)
        self.assertIn('rel="noopener noreferrer"', html)

    def test_application_start_does_not_import_editor_implementation(self):
        code = '''
import sys
from unittest.mock import patch
with patch('flask_apscheduler.APScheduler.start'):
    import app
for name in ('logic_data', 'logic_unity', 'logic_level_editor', 'utils.card_index', 'utils.deck_requests'):
    assert name not in sys.modules, name
'''
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
