from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from app import create_app
from security import normalize_ip


def application(**overrides):
    return create_app({"TESTING": True, "REQUEST_LIMIT_PER_IP": "2/minute",
                       "REQUEST_LIMIT_GLOBAL": "100/minute",
                       "TRUST_CLOUDFLARE_CLIENT_IP": False, **overrides})


def test_one_ip_budget_is_shared_by_aliases_methods_and_user_agents():
    client = application().test_client()
    assert client.get("/version", headers={"User-Agent": "PVZH-DIY"}).status_code == 200
    assert client.head("/api/version", headers={"User-Agent": "browser"}).status_code == 200
    with patch("blueprints.version.get_version_info", side_effect=AssertionError("must not read snapshot")):
        response = client.get("/version.txt", headers={"User-Agent": "new-agent"})
    assert response.status_code == 429
    assert response.json["code"] == "RATE_LIMITED"
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert response.json["retry_after"] == int(response.headers["Retry-After"])
    assert response.headers["Access-Control-Allow-Origin"] == "*"
    assert response.headers["Access-Control-Expose-Headers"] == "Retry-After"
    assert response.headers["Cache-Control"] == "no-store"
    assert "Content-Security-Policy" in response.headers


def test_independent_ip_and_global_budgets():
    client = application(REQUEST_LIMIT_GLOBAL="3/minute").test_client()
    for ip in ("192.0.2.1", "192.0.2.2", "192.0.2.3"):
        assert client.get("/version", environ_base={"REMOTE_ADDR": ip}).status_code == 200
    with patch("blueprints.version.get_version_info", side_effect=AssertionError("global budget must reject early")):
        assert client.get("/version", environ_base={"REMOTE_ADDR": "192.0.2.4"}).status_code == 429


def test_repeated_rejected_ip_does_not_drain_budget_of_other_users():
    client = application(REQUEST_LIMIT_PER_IP="1/minute", REQUEST_LIMIT_GLOBAL="2/minute").test_client()
    assert client.get("/version", environ_base={"REMOTE_ADDR": "192.0.2.1"}).status_code == 200
    for _ in range(10):
        assert client.get("/version", environ_base={"REMOTE_ADDR": "192.0.2.1"}).status_code == 429
    assert client.get("/version", environ_base={"REMOTE_ADDR": "192.0.2.2"}).status_code == 200


def test_untrusted_headers_do_not_create_new_identities():
    client = application().test_client()
    for number in range(3):
        response = client.get("/version", headers={"CF-Connecting-IP": f"192.0.2.{number}",
                                                   "X-Forwarded-For": f"198.51.100.{number}"})
        assert response.status_code == (200 if number < 2 else 429)


def test_configured_proxy_normalizes_ip_and_ignores_xff():
    client = application(TRUST_CLOUDFLARE_CLIENT_IP=True).test_client()
    for ip in ("::ffff:192.0.2.1", "192.0.2.1"):
        assert client.get("/version", headers={"CF-Connecting-IP": ip}).status_code == 200
    assert client.get("/version", headers={"CF-Connecting-IP": "192.0.2.1", "X-Forwarded-For": "198.51.100.6"}).status_code == 429
    assert client.get("/version", headers={"CF-Connecting-IP": "192.0.2.2"}).status_code == 200


@pytest.mark.parametrize("header", ["", "bad-ip", "192.0.2.1, 192.0.2.2", "fe80::1%eth0", "1" * 100])
def test_invalid_proxy_header_falls_back_to_peer(header):
    client = application(TRUST_CLOUDFLARE_CLIENT_IP=True, REQUEST_LIMIT_PER_IP="1/minute").test_client()
    assert client.get("/version").status_code == 200
    assert client.get("/version", headers={"CF-Connecting-IP": header}).status_code == 429


def test_health_is_the_only_exemption_and_errors_static_and_retired_are_counted():
    client = application().test_client()
    for _ in range(5):
        assert client.get("/health").status_code == 200
        assert client.head("/health").status_code == 200
    assert client.get("/missing").status_code == 404
    assert client.get("/unity").status_code == 410
    assert client.get("/static/site.css").status_code == 429
    assert client.get("/health").status_code == 200
    assert client.post("/health").status_code == 429


def test_window_recovers_without_sleeping_and_no_boundary_double_burst():
    client = application().test_client()
    with patch("time.time", return_value=2000000000):
        assert client.get("/version").status_code == 200
        assert client.get("/version").status_code == 200
    with patch("time.time", return_value=2000000059.9):
        assert client.get("/version").status_code == 429
    with patch("time.time", return_value=2000000060.1):
        assert client.get("/version").status_code == 200


def test_threaded_requests_cannot_overshoot_shared_budget():
    app = application(REQUEST_LIMIT_GLOBAL="5/minute", REQUEST_LIMIT_PER_IP="100/minute")
    def visit(number):
        with app.test_client() as client:
            return client.get("/version", environ_base={"REMOTE_ADDR": f"192.0.2.{number}"}).status_code
    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(visit, range(1, 21)))
    assert statuses.count(200) == 5
    assert statuses.count(429) == 15


def test_default_burst_and_sustained_rules_allow_normal_client_polling():
    app = create_app({"TESTING": True, "TRUST_CLOUDFLARE_CLIENT_IP": False})
    client = app.test_client()
    for path in ("/version", "/api/pvzh-launcher/v1/manifest.json", "/api/pvzh-diy/v1/featured/version.json", "/api/pvzh-diy/v1/featured/manifest.json", "/thanks"):
        assert client.get(path).status_code == 200
    # The first five calls used half of the short burst allowance.
    for _ in range(5):
        assert client.get("/version").status_code == 200
    assert client.get("/version").status_code == 429


def test_sustained_minute_budget_is_enforced_below_burst_limit():
    client = create_app({"TESTING": True}).test_client()
    for second in range(60):
        with patch("time.time", return_value=2000000000 + second):
            assert client.get("/version").status_code == 200
            assert client.get("/version").status_code == 200
    with patch("time.time", return_value=2000000059.5):
        assert client.get("/version").status_code == 429


@pytest.mark.parametrize("value,expected", [("2001:0DB8:0:0::1", "2001:db8::1"),
    ("::ffff:192.0.2.1", "192.0.2.1"), (None, None), ("invalid", None)])
def test_normalize_ip(value, expected):
    assert normalize_ip(value) == expected
