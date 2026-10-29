"""Project snapshot contract, hostile files and read-only HTTP isolation.

Use Flask's in-process client and temporary snapshots only; no server, scheduler,
network, production data writes, or environment credentials are needed.
"""
import copy
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from app import create_app
from blueprints import launcher_project as project


URL = "/api/pvzh-launcher/v1/project.json"
LIMIT = 64 * 1024
ROOT = Path(__file__).resolve().parents[1]


def valid_project():
    return {
        "schema_version": 1,
        "product": "pvzh-launcher",
        "updated_at": "2026-10-29",
        "title": "关于这个项目",
        "paragraphs": ["项目介绍第一段。", "第二段\n可以换行。"],
        "repository_note": "仓库目前为私人资料库。",
        "supporters": ["支持者甲"],
        "contributors": ["贡献者乙"],
    }


def write_snapshot(path, value, *, escaped=False):
    path.write_bytes(json.dumps(value, ensure_ascii=escaped,
                               separators=(",", ":")).encode("utf-8"))


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    path = tmp_path / "launcher-project.json"
    write_snapshot(path, valid_project())

    def data_path(name):
        assert name == "launcher-project.json"
        return str(path)

    monkeypatch.setattr(project, "data_file_path", data_path)
    return path


def application(**overrides):
    return create_app({
        "TESTING": True,
        "REQUEST_LIMIT_PER_IP": "10000/minute",
        "REQUEST_LIMIT_GLOBAL": "20000/minute",
        "TRUST_CLOUDFLARE_CLIENT_IP": False,
        **overrides,
    })


@pytest.fixture
def client(snapshot):
    return application().test_client()


def assert_headers(response):
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert "no-store" in response.headers["Cache-Control"]


def assert_unavailable(client, *, method="GET"):
    response = client.open(URL, method=method)
    assert response.status_code == 503
    assert_headers(response)
    if method == "HEAD":
        assert response.data == b""
    else:
        assert response.mimetype == "application/json"
        assert response.json["code"] == "LAUNCHER_PROJECT_UNAVAILABLE"
        assert "title" not in response.json
        assert "paragraphs" not in response.json
        assert "supporters" not in response.json
    return response


def test_valid_snapshot_uses_bounded_utf8_json_and_no_cache(client):
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json == valid_project()
    assert response.mimetype == "application/json"
    assert_headers(response)
    assert response.headers["Pragma"] == "no-cache"
    assert response.headers["Expires"] == "0"
    assert "关于这个项目".encode() in response.data
    assert len(response.data) <= LIMIT
    # This endpoint must not change the serializer used by existing APIs.
    assert client.application.json.ensure_ascii is True


def test_snapshot_changes_are_read_without_restarting(client, snapshot):
    first = client.get(URL).json
    changed = valid_project()
    changed.update(updated_at="2026-10-30", title="新介绍",
                   paragraphs=["新段落"], supporters=[], contributors=["新贡献者"])
    write_snapshot(snapshot, changed)
    assert first == valid_project()
    assert client.get(URL).json == changed


def test_committed_project_snapshot_matches_the_public_contract(client, snapshot):
    source = ROOT / "data" / "launcher-project.json"
    snapshot.write_bytes(source.read_bytes())
    response = client.get(URL)
    assert response.status_code == 200
    assert set(response.json) == set(valid_project())
    assert response.json["schema_version"] == 1
    assert response.json["product"] == "pvzh-launcher"
    assert_headers(response)


def test_head_has_get_status_and_headers_without_a_body(client):
    get = client.get(URL)
    head = client.head(URL)
    assert head.status_code == get.status_code == 200
    assert head.data == b""
    assert head.mimetype == "application/json"
    assert head.headers["Content-Length"] == get.headers["Content-Length"]
    assert_headers(head)


def test_options_does_not_read_a_missing_or_broken_snapshot(client, snapshot):
    snapshot.unlink()
    with patch.object(project, "launcher_project_snapshot",
                      side_effect=AssertionError("OPTIONS must not read files")):
        response = client.options(URL, headers={
            "Origin": "https://example.test", "Access-Control-Request-Method": "GET",
        })
    assert 200 <= response.status_code < 300
    assert_headers(response)


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_write_methods_are_405_without_reading_or_changing_files(client, snapshot, method):
    before = snapshot.read_bytes()
    with patch.object(project, "launcher_project_snapshot",
                      side_effect=AssertionError("rejected writes must not read files")):
        response = client.open(URL, method=method, json={"title": "do not save"})
    assert response.status_code == 405
    assert_headers(response)
    assert snapshot.read_bytes() == before


def test_missing_file_is_a_safe_json_503_including_head(client, snapshot):
    snapshot.unlink()
    response = assert_unavailable(client)
    assert str(snapshot).encode() not in response.data
    assert_unavailable(client, method="HEAD")


@pytest.mark.parametrize("raw", [b"\xff\xfe", b"\xef\xbb\xbf{}", b"{} {}",
                                 b"{", b"[]", b"null", b'"text"', b"true"])
def test_invalid_utf8_json_or_root_fails_closed(client, snapshot, raw):
    snapshot.write_bytes(raw)
    assert_unavailable(client)


def test_duplicate_keys_are_rejected_even_when_last_value_would_be_valid(client, snapshot):
    raw = json.dumps(valid_project(), ensure_ascii=False, separators=(",", ":"))
    for extra in ('"schema_version":1,', '"title":"injected",',
                  '"\\u0074itle":"injected",'):
        snapshot.write_text("{" + extra + raw[1:], encoding="utf-8")
        assert_unavailable(client)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_json_numbers_never_reach_the_response(client, snapshot, constant):
    raw = json.dumps(valid_project(), ensure_ascii=False, separators=(",", ":"))
    snapshot.write_text(raw.replace('"schema_version":1',
                                    '"schema_version":' + constant), encoding="utf-8")
    assert_unavailable(client)


def test_raw_64kib_boundary_is_inclusive(client, snapshot):
    raw = snapshot.read_bytes()
    snapshot.write_bytes(raw + b" " * (LIMIT - len(raw)))
    assert client.get(URL).status_code == 200
    snapshot.write_bytes(raw + b" " * (LIMIT + 1 - len(raw)))
    assert_unavailable(client)


def test_long_chinese_and_supplementary_unicode_fit_the_same_wire_limit(client, snapshot):
    value = valid_project()
    value["paragraphs"] = ["汉" * 1000 + "😀" * 100 for _ in range(12)]
    write_snapshot(snapshot, value)
    assert snapshot.stat().st_size < LIMIT
    response = client.get(URL)
    assert response.status_code == 200
    assert response.json == value
    assert "😀".encode() in response.data
    assert len(response.data) <= LIMIT


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", 0, 2, None])
def test_schema_is_exact_integer_one(client, snapshot, bad):
    value = valid_project(); value["schema_version"] = bad
    write_snapshot(snapshot, value)
    assert_unavailable(client)


@pytest.mark.parametrize("bad", ["pvzh-diy", "PVZH-Launcher", "", None, 1])
def test_product_is_exact_launcher_identifier(client, snapshot, bad):
    value = valid_project(); value["product"] = bad
    write_snapshot(snapshot, value)
    assert_unavailable(client)


def test_all_eight_keys_are_required_and_unknown_fields_are_rejected(client, snapshot):
    for key in valid_project():
        value = valid_project(); del value[key]
        write_snapshot(snapshot, value)
        assert_unavailable(client)
    value = valid_project(); value["repository_url"] = "https://example.test"
    write_snapshot(snapshot, value)
    assert_unavailable(client)


@pytest.mark.parametrize("bad", ["2026-02-30", "20261029", "2026-1-2",
                                 "2026-10-29T00:00:00Z", "2026-10-29Z", "", None, 1])
def test_updated_at_is_an_exact_valid_iso_date(client, snapshot, bad):
    value = valid_project(); value["updated_at"] = bad
    write_snapshot(snapshot, value)
    assert_unavailable(client)


def test_text_limits_use_unicode_codepoints_not_utf8_or_utf16_units(client, snapshot):
    value = valid_project()
    value.update(title="😀" * 120, paragraphs=["汉" * 2000],
                 repository_note="😀" * 400,
                 supporters=["😀" * 80], contributors=["汉" * 80])
    write_snapshot(snapshot, value)
    assert client.get(URL).json == value
    for key, limit in (("title", 120), ("repository_note", 400)):
        bad = copy.deepcopy(value); bad[key] = "😀" * (limit + 1)
        write_snapshot(snapshot, bad); assert_unavailable(client)
    for key, limit in (("paragraphs", 2000), ("supporters", 80), ("contributors", 80)):
        bad = copy.deepcopy(value); bad[key] = ["😀" * (limit + 1)]
        write_snapshot(snapshot, bad); assert_unavailable(client)


@pytest.mark.parametrize("key,limit", [("paragraphs", 20), ("supporters", 100),
                                      ("contributors", 100)])
def test_array_count_limits_and_empty_arrays(client, snapshot, key, limit):
    value = valid_project(); value[key] = []
    write_snapshot(snapshot, value)
    assert client.get(URL).json[key] == []
    value[key] = ["项"] * limit
    write_snapshot(snapshot, value)
    assert client.get(URL).json[key] == value[key]
    value[key].append("多余项")
    write_snapshot(snapshot, value)
    assert_unavailable(client)


@pytest.mark.parametrize("key", ["paragraphs", "supporters", "contributors"])
@pytest.mark.parametrize("bad", [None, "string", {}, [None], [False], [1],
                                 [["nested"]], [{"name": "object"}]])
def test_lists_are_plain_strings_only(client, snapshot, key, bad):
    value = valid_project(); value[key] = bad
    write_snapshot(snapshot, value)
    assert_unavailable(client)


def test_empty_paragraphs_are_allowed_but_name_entries_must_not_be_blank(client, snapshot):
    value = valid_project(); value["paragraphs"] = ["", " ", "\n\t"]
    write_snapshot(snapshot, value)
    assert client.get(URL).json == value
    for key in ("supporters", "contributors"):
        for blank in ("", " ", "\u0085", "\u00a0", "\u3000"):
            value = valid_project(); value[key] = [blank]
            write_snapshot(snapshot, value)
            assert_unavailable(client)


@pytest.mark.parametrize("key", ["title", "repository_note"])
@pytest.mark.parametrize("bad", [None, False, 1, [], {}])
def test_scalar_text_is_never_coerced_from_other_types(client, snapshot, key, bad):
    value = valid_project(); value[key] = bad
    write_snapshot(snapshot, value)
    assert_unavailable(client)


@pytest.mark.parametrize("key", ["title", "paragraphs", "repository_note", "supporters", "contributors"])
@pytest.mark.parametrize("bad", ["bad\ud800text", "bad\udffftext", "bad\x00text", "bad\ufffdtext"])
def test_invalid_unicode_or_controls_in_every_text_area_fail_closed(client, snapshot, key, bad):
    value = valid_project()
    value[key] = [bad] if key in ("paragraphs", "supporters", "contributors") else bad
    write_snapshot(snapshot, value, escaped=True)
    assert_unavailable(client)


def test_blank_title_is_rejected_but_empty_repository_note_is_allowed(client, snapshot):
    value = valid_project(); value["repository_note"] = ""
    write_snapshot(snapshot, value)
    assert client.get(URL).json["repository_note"] == ""
    for title in ("", " ", "\n\t"):
        value["title"] = title
        write_snapshot(snapshot, value); assert_unavailable(client)


def test_multiline_paragraphs_and_single_line_metadata_are_distinct(client, snapshot):
    value = valid_project(); value["paragraphs"] = ["first\nsecond\r\nthird\tlast"]
    write_snapshot(snapshot, value)
    assert client.get(URL).json == value
    for key in ("title", "repository_note", "supporters", "contributors"):
        value = valid_project()
        value[key] = ["two\nlines"] if key in ("supporters", "contributors") else "two\nlines"
        write_snapshot(snapshot, value)
        assert_unavailable(client)


def test_html_and_url_looking_content_remains_plain_json_data(client, snapshot):
    value = valid_project()
    value["paragraphs"] = ["<script>alert('x')</script>", "https://example.test/path"]
    value["repository_note"] = "<a href='https://example.test'>literal</a>"
    write_snapshot(snapshot, value)
    response = client.get(URL)
    assert response.status_code == 200 and response.json == value
    assert response.mimetype == "application/json"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_project_failures_do_not_modify_or_break_existing_service_snapshots(client, snapshot):
    old_files = [ROOT / "data" / name for name in
                 ("launcher.json", "version.json", "featured.json", "sponsors.json")]
    before = {p: p.read_bytes() for p in old_files}
    snapshot.write_bytes(b"{broken new project snapshot")
    assert_unavailable(client)
    for url in ("/version", "/api/version", "/version.txt",
                "/api/pvzh-launcher/v1/manifest.json",
                "/api/pvzh-diy/v1/featured/version.json",
                "/api/pvzh-diy/v1/featured/manifest.json", "/thanks"):
        response = client.get(url)
        assert response.status_code == 200, url
        if response.is_json:
            assert response.json.get("code") != "LAUNCHER_PROJECT_UNAVAILABLE"
    assert {p: p.read_bytes() for p in old_files} == before


def test_new_route_shares_existing_request_budget_and_is_rejected_before_snapshot_read(snapshot):
    client = application(REQUEST_LIMIT_PER_IP="1/minute").test_client()
    assert client.get("/version").status_code == 200
    with patch.object(project, "launcher_project_snapshot",
                      side_effect=AssertionError("rate limit must precede snapshot read")):
        response = client.get(URL, headers={"User-Agent": "different-agent"})
    assert response.status_code == 429
    assert response.json["code"] == "RATE_LIMITED"
    assert int(response.headers["Retry-After"]) >= 1
    assert_headers(response)
    assert client.get("/health").status_code == 200


def test_options_and_head_are_also_counted_by_request_protection(snapshot):
    client = application(REQUEST_LIMIT_PER_IP="2/minute").test_client()
    assert 200 <= client.options(URL).status_code < 300
    assert client.head(URL).status_code == 200
    with patch.object(project, "launcher_project_snapshot",
                      side_effect=AssertionError("shared method budget must reject first")):
        response = client.get("/api/pvzh-launcher/v1/project.json")
    assert response.status_code == 429
    assert_headers(response)
