"""Integration coverage for client compatibility and retiring the tool runtime."""
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

import pytest

from app import create_app
from blueprints.retired import TOOL_PATHS, WEB_PATHS

ROOT = Path(__file__).resolve().parents[1]
VERSION_URLS = ("/version", "/api/version", "/version.txt")
SPONSOR_URLS = ("/sponsors", "/api/sponsors", "/thanks", "/api/thanks", "/sponsors.txt", "/thanks.txt")


@pytest.fixture
def client():
    return create_app({"TESTING": True}).test_client()


@pytest.mark.parametrize("url,filename", [(url, "version.json") for url in VERSION_URLS]
                         + [(url, "sponsors.json") for url in SPONSOR_URLS])
def test_legacy_aliases_keep_committed_payloads_and_headers(client, url, filename):
    response = client.get(url, headers={"User-Agent": "curl/8.0", "Accept": "application/json"})
    assert response.status_code == 200
    assert response.json == json.loads((ROOT / "data" / filename).read_text())
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "no-store" in response.headers["Cache-Control"]
    assert client.head(url).status_code == 200
    assert client.post(url).status_code == 405


def test_launcher_and_featured_are_still_available_in_real_app(client):
    urls = ("/api/pvzh-launcher/v1/manifest.json", "/api/pvzh-diy/v1/featured/manifest.json",
            "/api/pvzh-diy/v1/featured/version.json")
    for url in urls:
        response = client.get(url, headers={"User-Agent": "PVZH-Launcher/1.0"})
        assert response.status_code == 200
        assert response.is_json
        assert "no-store" in response.headers["Cache-Control"]
        assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert client.head(url).status_code == 200
        assert client.post(url).status_code == 405


def test_index_is_only_a_transition_notice(client):
    response = client.get("/")
    text = response.get_data(as_text=True)
    assert response.status_code == 200
    for expected in ("PVZH Mod 启动器", "逐步搬到启动器", "迁移仍在进行中", "感谢",
                     'href="https://m.bilibili.com/space/1578548705"'):
        assert expected in text
    for removed in ("<script", "<nav", "<form", "<dialog", "localStorage", "vue", "tailwind",
                    'href="/unity"', 'href="/downloads"', 'href="/tools"', "sponsors", "featured"):
        assert removed not in text
    assert "unsafe-inline" not in response.headers["Content-Security-Policy"]
    assert client.get("/static/site.css").status_code == 200


@pytest.mark.parametrize("url", WEB_PATHS)
def test_old_web_pages_are_gone_with_a_notice(client, url):
    response = client.get(url)
    assert response.status_code == 410
    assert 'href="/"' in response.get_data(as_text=True)
    assert "noindex, follow" in response.get_data(as_text=True)
    assert "no-store" in response.headers["Cache-Control"]
    assert client.head(url).status_code == 410


@pytest.mark.parametrize("url", TOOL_PATHS)
@pytest.mark.parametrize("method", ("GET", "POST", "PUT", "PATCH", "DELETE"))
def test_retired_tools_ignore_even_invalid_oversize_bodies(client, url, method):
    # Werkzeug only parses/limits a body on access; tombstones must never read it.
    response = client.open(url, method=method, data=b"invalid JSON, not a Bundle",
                           content_type="application/json", environ_overrides={"CONTENT_LENGTH": str(200 * 1024 * 1024)})
    assert response.status_code == 410
    assert response.json["code"] == "WEB_TOOLS_RETIRED"
    assert response.json["archived"] is True


def test_robots_and_sitemap_only_advertise_configured_homepage():
    client = create_app({"TESTING": True, "SITE_BASE_URL": "https://versions.example.org"}).test_client()
    xml = client.get("/sitemap.xml")
    root = ElementTree.fromstring(xml.data)
    locations = [node.text for node in root.findall(".//{*}loc")]
    assert locations == ["https://versions.example.org/"]
    assert "Sitemap: https://versions.example.org/sitemap.xml" in client.get("/robots.txt").text
    assert 'href="https://versions.example.org/"' in client.get("/").text


def test_removed_files_and_security_admin_are_not_public(client):
    for path in ("/static/vendor/vue-3.5.13.global.prod.js", "/static/vendor/tailwind.css",
                 "/static/js/phantom/main.js", "/static/images/thanks/No1.jpg",
                 "/archive/editors/data/decks.json", "/security/stats"):
        assert client.get(path).status_code == 404
    assert client.get("/health").json == {"status": "ok"}


def test_startup_needs_no_tool_database_or_scheduler_packages():
    code = '''
import sys
from app import app
assert app.test_client().get('/health').status_code == 200
for module in ('UnityPy', 'supabase', 'requests', 'flask_apscheduler', 'security', 'database', 'extensions'):
    assert module not in sys.modules, module
'''
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("field,value", [("version_code", True), ("version_code", -1),
    ("force_update", "true"), ("release_date", "2026-02-30"), ("download_url", "javascript:alert(1)"),
    ("minimum_supported_version_code", 99999999), ("update_title", None)])
def test_bad_diy_snapshots_fail_closed_without_old_version_fallback(client, field, value):
    data = json.loads((ROOT / "data/version.json").read_text())
    data[field] = value
    with patch("blueprints.version.load_json_file", return_value=data):
        response = client.get("/version")
    assert response.status_code == 503
    assert response.json["code"] == "VERSION_UNAVAILABLE"
    assert "version_code" not in response.json
    assert "no-store" in response.headers["Cache-Control"]


def test_missing_diy_snapshot_is_503(client):
    with patch("blueprints.version.load_json_file", return_value=None):
        assert client.get("/version").status_code == 503


@pytest.mark.parametrize("raw", [b'{} {}', b'{"x":1,"x":2}', b'{"x":NaN}', b'\xff', b' ' * 131073])
def test_shared_snapshot_loader_rejects_invalid_or_large_json(tmp_path, raw):
    from utils.json_data import load_json_file
    file = tmp_path / "snapshot.json"
    file.write_bytes(raw)
    with patch("utils.json_data.data_file_path", return_value=str(file)):
        assert load_json_file("snapshot.json") is None
