import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from blueprints.featured import featured_bp
from blueprints.version import version_bp

class PublicCatalogTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.file = Path(self.temp.name) / "featured.json"
        self.file.write_text(json.dumps({"schema_version": 2, "featured_version": "test-1", "works": []}), encoding="utf-8")
        app = Flask(__name__)
        app.register_blueprint(featured_bp)
        app.register_blueprint(version_bp)
        self.client = app.test_client()
        self.path_patch = patch("blueprints.featured.data_file_path", return_value=str(self.file))
        self.path_patch.start()
    def tearDown(self):
        self.path_patch.stop(); self.temp.cleanup()
    def test_empty_version_and_manifest_agree(self):
        for name in ("version", "manifest"):
            response = self.client.get("/api/pvzh-diy/v1/featured/" + name + ".json", headers={"User-Agent": "PVZH-DIY/4.13.1"})
            self.assertEqual(200, response.status_code)
            self.assertEqual("test-1", response.json["featured_version"])
            self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual([], self.client.get("/api/pvzh-diy/v1/featured/manifest.json").json["works"])
    def test_bad_snapshot_returns_503_not_fake_empty_success(self):
        self.file.write_text("{}")
        self.assertEqual(503, self.client.get("/api/pvzh-diy/v1/featured/version.json").status_code)
        self.file.write_bytes(b" " * 131073)
        self.assertEqual(503, self.client.get("/api/pvzh-diy/v1/featured/manifest.json").status_code)
    def test_malformed_snapshot_types_are_503(self):
        for value in ([], {"schema_version": 2, "featured_version": "v1", "works": [None]},
                      {"schema_version": 2, "featured_version": "v1", "works": []}):
            self.file.write_text(json.dumps(value))
            expected = 200 if isinstance(value, dict) and value.get("works") == [] else 503
            self.assertEqual(expected, self.client.get("/api/pvzh-diy/v1/featured/manifest.json").status_code)
    def test_existing_version_aliases_keep_seven_fields(self):
        old = {"version": "v4.13.1", "version_code": 41301, "force_update": True,
               "download_url": "https://example.org", "update_title": "旧客户端", "update_log": "兼容", "release_date": "2026-10-03"}
        with patch("blueprints.version.load_json_file", return_value=old):
            for path in ("/version", "/api/version", "/version.txt"):
                result = self.client.get(path).json
                for key, value in old.items(): self.assertEqual(value, result[key])
                self.assertIsNone(result["minimum_supported_version"])
                self.assertIsNone(result["minimum_supported_version_code"])
    def test_catalog_rejects_unpinned_or_unknown_image_host(self):
        entry = {"id": "w1", "sha256": "a" * 64, "author_id": "作者", "image_url": "https://example.org/a.png"}
        self.file.write_text(json.dumps({"schema_version": 2, "featured_version": "test-1", "works": [entry]}))
        self.assertEqual(503, self.client.get("/api/pvzh-diy/v1/featured/manifest.json").status_code)
