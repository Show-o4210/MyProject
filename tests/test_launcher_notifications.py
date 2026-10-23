"""Launcher snapshot tests; no production app import, scheduler or network.

Can also run from an isolated staging tree when the original project is on
PYTHONPATH. This is the same file used after integration into the web project.
"""
import copy
import importlib.util
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from blueprints.version import version_bp

_module_path = Path(__file__).resolve().parents[1] / "blueprints" / "launcher.py"
_spec = importlib.util.spec_from_file_location("launcher_notifications_under_test", _module_path)
launcher = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(launcher)
URL = "/api/pvzh-launcher/v1/manifest.json"


def valid_manifest():
    return {
        "schema_version": 1,
        "product": "pvzh-launcher",
        "channel": "stable",
        "latest": {
            "release_code": 22001,
            "version": "R22 RC1",
            "title": "版本提醒",
            "notes": "第一行\n第二行",
            "download_url": "https://pvz-h-tools.onrender.com/downloads",
        },
        "announcements": [{
            "id": "notice-1", "title": "公告入口已上线",
            "content": "公告正文", "published_at": "2026-10-23",
        }],
    }


class LauncherNotificationsTest(unittest.TestCase):
    def setUp(self):
        # Inherit the normal parent ACL. Python 3.14's Windows mode=0o700
        # TemporaryDirectory ACL can exclude a restricted process's own SID.
        self.temp = Path(tempfile.gettempdir()) / ("pvzh-launcher-test-" + uuid.uuid4().hex)
        self.temp.mkdir()
        self.file = self.temp / "launcher.json"
        self.addCleanup(self.cleanup_snapshot)
        self.write(valid_manifest())
        path_patch = patch.object(launcher, "data_file_path", return_value=str(self.file))
        path_patch.start()
        self.addCleanup(path_patch.stop)
        app = Flask(__name__)
        app.testing = True
        app.register_blueprint(launcher.launcher_bp)
        app.register_blueprint(version_bp)
        self.client = app.test_client()

    def cleanup_snapshot(self):
        self.file.unlink(missing_ok=True)
        self.temp.rmdir()

    def write(self, value):
        self.file.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

    def assert_unavailable(self):
        response = self.client.get(URL)
        self.assertEqual(503, response.status_code)
        self.assertEqual("LAUNCHER_MANIFEST_UNAVAILABLE", response.json["code"])
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertNotIn("latest", response.json)
        return response

    def test_valid_response_is_no_cache_and_cors_enabled(self):
        response = self.client.get(URL)
        self.assertEqual(200, response.status_code)
        self.assertEqual(valid_manifest(), response.json)
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual("no-cache", response.headers["Pragma"])
        self.assertEqual("0", response.headers["Expires"])
        self.assertEqual("*", response.headers["Access-Control-Allow-Origin"])

    def test_snapshot_is_read_each_time_without_version_announcement_tearing(self):
        first = self.client.get(URL).json
        value = valid_manifest()
        value["latest"]["release_code"] = 23001
        value["announcements"][0]["id"] = "notice-2"
        self.write(value)
        second = self.client.get(URL).json
        self.assertEqual(22001, first["latest"]["release_code"])
        self.assertEqual(23001, second["latest"]["release_code"])
        self.assertEqual("notice-2", second["announcements"][0]["id"])

    def test_empty_announcements_are_valid(self):
        value = valid_manifest(); value["announcements"] = []
        self.write(value)
        self.assertEqual([], self.client.get(URL).json["announcements"])

    def test_only_get_and_implicit_head_have_read_access(self):
        self.assertEqual(200, self.client.head(URL).status_code)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method):
                self.assertEqual(405, self.client.open(URL, method=method).status_code)

    def test_missing_file_or_invalid_utf8_or_trailing_json_returns_503(self):
        self.file.unlink()
        self.assert_unavailable()
        for raw in (b"\xff\xfe", b"{} {}", b"{", b"\xef\xbb\xbf{}"):
            with self.subTest(raw=raw):
                self.file.write_bytes(raw)
                self.assert_unavailable()

    def test_size_boundary_and_oversize_rejected(self):
        raw = json.dumps(valid_manifest()).encode("utf-8")
        self.file.write_bytes(raw + b" " * (launcher.MAX_BYTES - len(raw)))
        self.assertEqual(200, self.client.get(URL).status_code)
        self.file.write_bytes(raw + b" " * (launcher.MAX_BYTES + 1 - len(raw)))
        self.assert_unavailable()

    def test_long_chinese_snapshot_stays_inside_client_wire_limit(self):
        value = valid_manifest()
        value["latest"]["notes"] = "汉" * 8000
        value["announcements"][0]["content"] = "字" * 8000
        self.write(value)
        self.assertLess(self.file.stat().st_size, launcher.MAX_BYTES)
        response = self.client.get(URL)
        self.assertEqual(200, response.status_code)
        self.assertEqual(value, response.json)
        self.assertLessEqual(len(response.data), launcher.MAX_BYTES)
        self.assertIn("汉".encode("utf-8"), response.data)
        self.assertEqual("application/json", response.mimetype)
        self.assertTrue(self.client.application.json.ensure_ascii)

    def test_duplicate_properties_and_non_json_numbers_rejected(self):
        for raw in ('{"schema_version":1,"schema_version":1}',
                    '{"extra":NaN}', '{"extra":Infinity}', '{"extra":-Infinity}'):
            self.file.write_text(raw, encoding="utf-8")
            self.assert_unavailable()

    def test_integer_contracts_reject_boolean_float_negative_and_overflow(self):
        for key, values in (("schema_version", (True, 1.0, "1", 2)),
                            ("release_code", (True, 22001.0, "22001", 0, -1, 2147483648))):
            for bad in values:
                with self.subTest(key=key, bad=bad):
                    value = valid_manifest()
                    target = value if key == "schema_version" else value["latest"]
                    target[key] = bad
                    self.write(value); self.assert_unavailable()

    def test_wrong_top_level_and_missing_fields_are_rejected(self):
        cases = [[], None, {}, valid_manifest(), valid_manifest(), valid_manifest()]
        cases[3]["product"] = "pvzh-diy"
        cases[4]["channel"] = "beta"
        cases[5]["latest"] = []
        for value in cases:
            with self.subTest(value=value):
                self.write(value); self.assert_unavailable()
        for key in valid_manifest()["latest"]:
            value = valid_manifest(); del value["latest"][key]
            self.write(value); self.assert_unavailable()

    def test_only_official_https_download_hosts_are_allowed(self):
        for url in ("https://pvz-h-tools.onrender.com/downloads",
                    "https://pan.quark.cn/s/example", "https://pan.quark.cn:443/s/example"):
            value = valid_manifest(); value["latest"]["download_url"] = url
            self.write(value); self.assertEqual(200, self.client.get(URL).status_code)
        for url in ("http://pan.quark.cn/s/example", "https://evil.example/a",
                    "https://pan.quark.cn.evil.example/a", "https://u:p@pan.quark.cn/a",
                    "https://@pan.quark.cn/a", "https://pan.quark.cn:444/a",
                    "https://pan.quark.cn/a#fragment", "https://pan.quark.cn/a#",
                    "https://pan.quark.cn/a b", "https://pan.quark.cn\\@evil.example/a",
                    "https://pan.quark.cn:invalid/a", "https://[invalid/a"):
            with self.subTest(url=url):
                value = valid_manifest(); value["latest"]["download_url"] = url
                self.write(value); self.assert_unavailable()

    def test_duplicate_invalid_or_excessive_announcement_ids_rejected(self):
        value = valid_manifest(); value["announcements"] *= 2
        self.write(value); self.assert_unavailable()
        for identifier in (None, 12, "", "bad id", "x" * 81):
            value = valid_manifest(); value["announcements"][0]["id"] = identifier
            self.write(value); self.assert_unavailable()
        value = valid_manifest()
        value["announcements"] = [{**value["announcements"][0], "id": f"n-{i}"} for i in range(30)]
        self.write(value); self.assertEqual(200, self.client.get(URL).status_code)
        value["announcements"].append({**value["announcements"][0], "id": "n-31"})
        self.write(value); self.assert_unavailable()

    def test_wrong_announcement_types_and_dates_are_rejected(self):
        for announcements in (None, {}, [None], [False]):
            value = valid_manifest(); value["announcements"] = announcements
            self.write(value); self.assert_unavailable()
        for date in ("2026-02-30", "20261023", "2026-10-23Z", None):
            value = valid_manifest(); value["announcements"][0]["published_at"] = date
            self.write(value); self.assert_unavailable()

    def test_bad_unicode_controls_blank_or_long_text_are_rejected(self):
        for key, bad in (("title", ""), ("title", " \n"), ("title", "x" * 121),
                         ("title", 12), ("title", "bad\x00text"),
                         ("notes", "bad\ufffdtext"), ("notes", "bad\ud800text"),
                         ("notes", "x" * 8001)):
            value = valid_manifest(); value["latest"][key] = bad
            self.file.write_text(json.dumps(value, ensure_ascii=True), encoding="utf-8")
            self.assert_unavailable()
        for key in ("title", "content"):
            value = valid_manifest(); value["announcements"][0][key] = []
            self.write(value); self.assert_unavailable()

    def test_unexpected_fields_are_not_exposed(self):
        value = valid_manifest(); value["internal"] = "not public"
        value["latest"]["internal"] = "not public"
        value["announcements"][0]["internal"] = "not public"
        self.write(value)
        self.assertEqual(valid_manifest(), self.client.get(URL).json)

    def test_existing_diy_version_routes_keep_their_contract(self):
        old = {"version": "v5.1.0", "version_code": 50100, "force_update": True,
               "download_url": "https://pan.quark.cn/s/example", "update_title": "DIY",
               "update_log": "旧合同", "release_date": "2026-10-16"}
        with patch("blueprints.version.load_json_file", return_value=copy.deepcopy(old)):
            for url in ("/version", "/api/version", "/version.txt"):
                response = self.client.get(url)
                for key, value in old.items():
                    self.assertEqual(value, response.json[key])
                self.assertIsNone(response.json["minimum_supported_version"])
                self.assertIsNone(response.json["minimum_supported_version_code"])

    def test_committed_default_snapshot_is_valid(self):
        source = Path(__file__).resolve().parents[1] / "data" / "launcher.json"
        self.file.write_bytes(source.read_bytes())
        response = self.client.get(URL)
        self.assertEqual(200, response.status_code)
        self.assertEqual(22001, response.json["latest"]["release_code"])
        self.assertEqual("https://pan.quark.cn/s/35c024ea8e02", response.json["latest"]["download_url"])


if __name__ == "__main__":
    unittest.main()
