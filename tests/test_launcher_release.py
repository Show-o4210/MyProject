"""Stable release conversion, hostile snapshots and old API isolation."""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app import create_app
from blueprints import launcher_release as release

ROOT = Path(__file__).resolve().parents[1]
URL = "/api/pvzh-launcher/v2/manifest.json"
LIMIT = 64 * 1024


def valid_release():
    return {
        "schema_version": 1, "product": "pvzh-launcher", "public_version": "v1",
        "release_code": 100001, "internal_revision": "R51", "channel": "stable",
        "release_date": "2026-10-30", "title": "正式版",
        "notes": "第一行\n第二行", "download_url": "https://pan.quark.cn/s/example",
    }


def notifications():
    return json.loads((ROOT / "data/launcher.json").read_text(encoding="utf-8"))


def write(path, value):
    path.write_bytes(json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode())


def application(**overrides):
    return create_app({"TESTING": True, "REQUEST_LIMIT_PER_IP": "10000/minute",
                       "REQUEST_LIMIT_GLOBAL": "20000/minute",
                       "TRUST_CLOUDFLARE_CLIENT_IP": False, **overrides})


@pytest.fixture
def snapshots(tmp_path, monkeypatch):
    paths = {name: tmp_path / name for name in ("launcher-release.json", "launcher.json")}
    write(paths["launcher-release.json"], valid_release())
    write(paths["launcher.json"], notifications())
    monkeypatch.setattr(release, "data_file_path", lambda name: str(paths[name]))
    return paths


@pytest.fixture
def client(snapshots):
    return application().test_client()


def headers(response):
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "no-store" in response.headers["Cache-Control"]
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"


def unavailable(client, method="GET"):
    response = client.open(URL, method=method)
    assert response.status_code == 503
    headers(response)
    if method == "HEAD":
        assert response.data == b""
    else:
        assert response.json["code"] == "LAUNCHER_MANIFEST_UNAVAILABLE"
        assert "latest" not in response.json
    return response


def test_committed_identity_maps_to_five_public_fields():
    data = json.loads((ROOT / "data/launcher-release.json").read_text(encoding="utf-8"))
    assert len(data) == 10
    assert data["public_version"] == "v1"
    assert data["release_code"] == 100001
    assert data["internal_revision"] == "R51"
    assert data["release_date"] == "2026-10-30"
    response = application().test_client().get(URL)
    assert response.status_code == 200
    assert response.json == {
        "schema_version": 1, "product": "pvzh-launcher", "channel": "stable",
        "latest": {"release_code": data["release_code"], "version": data["public_version"],
                   "title": data["title"], "notes": data["notes"],
                   "download_url": data["download_url"]},
        "announcements": notifications()["announcements"],
    }
    headers(response)
    assert response.mimetype == "application/json"
    assert "internal_revision" not in response.json["latest"]
    assert "release_date" not in response.json["latest"]


def test_snapshot_is_read_on_each_request_and_normal_announcements_share_source(client, snapshots):
    first = client.get(URL).json
    identity = valid_release(); identity["release_code"] = 100002
    notice = notifications(); notice["announcements"][0]["content"] = "最新普通公告"
    write(snapshots["launcher-release.json"], identity)
    write(snapshots["launcher.json"], notice)
    second = client.get(URL).json
    assert first["latest"]["release_code"] == 100001
    assert second["latest"]["release_code"] == 100002
    assert second["announcements"] == notice["announcements"]


@pytest.mark.parametrize("field,bad", [
    ("schema_version", True), ("schema_version", 1.0), ("schema_version", "1"),
    ("schema_version", 2), ("product", "pvzh-diy"), ("channel", "development"),
    ("release_code", True), ("release_code", 100001.0), ("release_code", "100001"),
    ("release_code", 0), ("release_code", -1), ("release_code", 2147483648),
    ("public_version", "R51"), ("public_version", "v0"), ("public_version", "v01"),
    ("public_version", "v1.01"), ("public_version", "v1.1.01"),
    ("public_version", "v1.1.1.1"), ("public_version", "v1-beta"),
    ("public_version", "v1\n"), ("public_version", "v" + "1" * 80),
    ("internal_revision", "R0"), ("internal_revision", "R051"),
    ("internal_revision", "R51 RC1"), ("internal_revision", "r51"),
    ("release_date", "2026-02-30"), ("release_date", "20261030"),
    ("release_date", "2026-10-30Z"), ("release_date", "2026-1-01"),
    ("title", ""), ("title", "\u0085\u2003"), ("title", "x" * 121),
    ("title", 42), ("title", "bad\x00"), ("notes", "bad\ufffd"),
    ("notes", "bad\ud800"), ("notes", "bad\x7f"), ("notes", "x" * 8001),
])
def test_invalid_identity_returns_unavailable(client, snapshots, field, bad):
    identity = valid_release(); identity[field] = bad
    write(snapshots["launcher-release.json"], identity)
    unavailable(client)


@pytest.mark.parametrize("field", sorted(release.FIELDS))
def test_all_identity_fields_are_required(client, snapshots, field):
    identity = valid_release(); del identity[field]
    write(snapshots["launcher-release.json"], identity)
    unavailable(client)


@pytest.mark.parametrize("value", [None, [], {}, False, {**valid_release(), "extra": "hidden"}])
def test_exact_identity_root(client, snapshots, value):
    write(snapshots["launcher-release.json"], value)
    unavailable(client)


@pytest.mark.parametrize("version", ["v1", "v12", "v1.0", "v1.1", "v1.0.1", "v999.10.0"])
def test_public_version_patch_and_minor_forms_are_supported(client, snapshots, version):
    identity = valid_release(); identity["public_version"] = version
    write(snapshots["launcher-release.json"], identity)
    assert client.get(URL).json["latest"]["version"] == version


def test_valid_boundaries_preserve_original_text_and_unicode_codepoints(client, snapshots):
    identity = valid_release()
    identity.update(release_code=2147483647, release_date="2000-02-29", title="😀" * 120,
                    notes="\n\r\t" + "字" * 7997)
    write(snapshots["launcher-release.json"], identity)
    # Escaped UTF-16 pairs can exceed raw cap; UTF-8 form is within the cap.
    snapshots["launcher-release.json"].write_bytes(json.dumps(identity, ensure_ascii=False).encode())
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json["latest"]["title"] == identity["title"]
    assert response.json["latest"]["notes"] == identity["notes"]
    assert "字".encode() in response.data
    assert len(response.data) <= LIMIT
    identity["notes"] = ""
    write(snapshots["launcher-release.json"], identity)
    assert client.get(URL).json["latest"]["notes"] == ""


@pytest.mark.parametrize("url", [
    "http://pan.quark.cn/s/x", "https://evil.example/s/x", "https://pan.quark.cn.evil/a",
    "https://u:p@pan.quark.cn/a", "https://@pan.quark.cn/a", "https://pan.quark.cn:444/a",
    "https://pan.quark.cn/a#x", "https://pan.quark.cn/a#", "https://pan.quark.cn/a b",
    "https://pan.quark.cn\\@evil.example/a", "https://pan.quark.cn:bad/a", "https://[bad/a",
])
def test_download_hosts_remain_bounded_and_https_only(client, snapshots, url):
    identity = valid_release(); identity["download_url"] = url
    write(snapshots["launcher-release.json"], identity)
    unavailable(client)


@pytest.mark.parametrize("url", ["https://pan.quark.cn/s/x", "https://pan.quark.cn:443/s/x",
                                  "https://pvz-h-tools.onrender.com/downloads"])
def test_existing_allowed_download_hosts(client, snapshots, url):
    identity = valid_release(); identity["download_url"] = url
    write(snapshots["launcher-release.json"], identity)
    assert client.get(URL).json["latest"]["download_url"] == url


@pytest.mark.parametrize("name", ["launcher-release.json", "launcher.json"])
@pytest.mark.parametrize("raw", [b"\xff", b"\xef\xbb\xbf{}", b"{} {}", b"{",
                                  b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}',
                                  b'{"x":1e999}', b'{"x":1,"x":2}',
                                  b'{"x":{"nested":1,"nested":2}}'])
def test_invalid_raw_snapshots_fail_closed(client, snapshots, name, raw):
    snapshots[name].write_bytes(raw)
    unavailable(client)


@pytest.mark.parametrize("name", ["launcher-release.json", "launcher.json"])
def test_missing_and_raw_size_limits(client, snapshots, name):
    original = snapshots[name].read_bytes()
    snapshots[name].write_bytes(original + b" " * (LIMIT - len(original)))
    assert client.get(URL).status_code == 200
    snapshots[name].write_bytes(original + b" " * (LIMIT + 1 - len(original)))
    unavailable(client)
    snapshots[name].unlink()
    unavailable(client)


def test_combined_wire_size_is_checked_even_if_both_source_files_fit(client, snapshots):
    identity = valid_release(); identity["notes"] = "字" * 8000
    notice = notifications()
    notice["announcements"] = [
        {"id": str(i), "title": "公告", "content": "汉" * 8000, "published_at": "2026-10-30"}
        for i in range(2)
    ]
    for name, value in [("launcher-release.json", identity), ("launcher.json", notice)]:
        snapshots[name].write_bytes(json.dumps(value, ensure_ascii=False).encode())
        assert snapshots[name].stat().st_size < LIMIT
    unavailable(client)


@pytest.mark.parametrize("bad", [None, {}, [None], [False]])
def test_invalid_announcement_lists(client, snapshots, bad):
    notice = notifications(); notice["announcements"] = bad
    write(snapshots["launcher.json"], notice)
    unavailable(client)


@pytest.mark.parametrize("field,bad", [
    ("id", "bad id"), ("id", "x" * 81), ("id", 2),
    ("published_at", "2026-02-30"), ("published_at", "20261030"),
    ("title", ""), ("title", "x" * 121), ("content", ""),
    ("content", "x" * 8001), ("content", "bad\udfff"), ("content", "bad\x00"),
])
def test_invalid_announcements(client, snapshots, field, bad):
    notice = notifications(); notice["announcements"][0][field] = bad
    write(snapshots["launcher.json"], notice)
    unavailable(client)


def test_announcement_limits_duplicate_ids_and_no_unknown_field_transmission(client, snapshots):
    notice = notifications(); item = notice["announcements"][0]
    item["private_extra"] = "hidden"
    notice["private_extra"] = {"secret": "hidden"}
    notice["latest"] = None  # Old latest is neither validated nor reused by v2.
    write(snapshots["launcher.json"], notice)
    result = client.get(URL).json
    assert "private_extra" not in result
    assert "private_extra" not in result["announcements"][0]
    assert result["latest"]["version"] == "v1"
    notice["announcements"] = [{**item, "id": str(i)} for i in range(30)]
    write(snapshots["launcher.json"], notice)
    assert client.get(URL).status_code == 200
    notice["announcements"].append({**item, "id": "31"})
    write(snapshots["launcher.json"], notice); unavailable(client)
    notice["announcements"] = [item, copy.deepcopy(item)]
    write(snapshots["launcher.json"], notice); unavailable(client)
    notice["announcements"] = []
    write(snapshots["launcher.json"], notice)
    assert client.get(URL).json["announcements"] == []


def test_discarded_source_strings_cannot_hide_invalid_unicode(client, snapshots):
    notice = notifications(); notice["discarded"] = "\ud800"
    write(snapshots["launcher.json"], notice)
    unavailable(client)


def test_head_get_errors_options_and_writes(client, snapshots):
    get = client.get(URL); head = client.head(URL)
    assert head.status_code == get.status_code == 200
    assert head.data == b""
    assert head.headers["Content-Length"] == get.headers["Content-Length"]
    headers(head)
    snapshots["launcher-release.json"].unlink()
    unavailable(client, "HEAD")
    with patch.object(release, "_read_snapshot", side_effect=AssertionError("must not read")):
        options = client.options(URL)
        assert options.status_code == 200
        assert options.headers["Access-Control-Allow-Methods"] == "GET, HEAD, OPTIONS"
        headers(options)
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            response = client.open(URL, method=method)
            assert response.status_code == 405
            headers(response)


def test_new_config_failure_cannot_change_any_old_client_response(client, snapshots):
    urls = ["/version", "/api/version", "/version.txt", "/api/pvzh-launcher/v1/manifest.json",
            "/api/pvzh-launcher/v1/project.json", "/api/pvzh-diy/v1/featured/version.json",
            "/api/pvzh-diy/v1/featured/manifest.json", "/api/sponsors"]
    before = {url: client.get(url).json for url in urls}
    assert all(value is not None for value in before.values())
    snapshots["launcher-release.json"].write_bytes(b"invalid release")
    unavailable(client)
    for url, expected in before.items():
        response = client.get(url)
        assert response.status_code == 200
        assert response.json == expected
    assert before["/api/pvzh-launcher/v1/manifest.json"]["latest"]["release_code"] == 22001


def test_v2_uses_existing_cross_route_request_budget(snapshots):
    client = application(REQUEST_LIMIT_PER_IP="1/minute").test_client()
    assert client.get("/api/pvzh-launcher/v1/project.json").status_code == 200
    with patch.object(release, "_read_snapshot", side_effect=AssertionError("must not read")):
        response = client.get(URL)
    assert response.status_code == 429
    assert response.json["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) >= 1
    headers(response)
