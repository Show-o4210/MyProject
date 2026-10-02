"""Security audit regression tests; no live Supabase calls or app scheduler."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import unittest
from unittest.mock import Mock, patch

from flask import Flask

from extensions import init_limiter, limiter
import security


class SecurityAuditTests(unittest.TestCase):
    BLOCKED_IP = "60.27.42.212"
    HEADERS = {"User-Agent": "Mozilla/5.0"}

    def setUp(self):
        security._recent_log_keys.clear()
        self.addCleanup(security._recent_log_keys.clear)
        self.clock = Mock(return_value=1000.0)
        self.db = Mock()
        self.insert = self.db.table.return_value.insert
        self.execute = self.insert.return_value.execute
        for target, value in (
            ("security.get_supabase", Mock(return_value=self.db)),
            ("security.time.time", self.clock),
            ("security.time.monotonic", self.clock),
            ("security.LOG_DEDUP_SECONDS", 300),
            ("security.BLOCKED_IPS", {self.BLOCKED_IP}),
            ("security.TRUSTED_IPS", set()),
            ("security.SELF_PING_TOKEN", ""),
            ("security.ABUSE_TEXT_PATTERNS", ["test-abuse"]),
            ("security._supabase_log_fail_count", 0),
            ("security._supabase_log_last_warn", 0.0),
            ("builtins.print", Mock()),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = Flask(__name__)
        self.app.testing = True
        security.init_security_handlers(self.app)
        self.app.add_url_rule("/health", "health", lambda: {"status": "ok"})
        # Match app.py's ordering without importing its background scheduler.
        init_limiter(self.app)
        limiter.reset()
        self.addCleanup(limiter.reset)
        self.route = Mock(return_value="business response")
        self.app.add_url_rule(
            "/<path:path>", "business", lambda path: self.route(path=path),
            methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        )
        self.client = self.app.test_client()

    def request(self, path, method="GET", ip=None, headers=None, client=None, **kwargs):
        return (client or self.client).open(
            path, method=method, headers=headers or self.HEADERS,
            environ_overrides={"REMOTE_ADDR": ip or self.BLOCKED_IP}, **kwargs,
        )

    def test_repeated_sensitive_requests_keep_403_with_one_insert(self):
        # Exceed the normal 400/hour limit: blocked responses still take precedence.
        for index in range(450):
            response = self.request(f"/admin/resource-{index}")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json(), {"error": "Forbidden"})
        self.assertEqual(self.insert.call_count, 1)
        self.assertEqual(self.execute.call_count, 1)
        self.assertTrue(self.insert.call_args.args[0]["blocked"])
        self.route.assert_not_called()

    def test_repeated_shadow_bans_keep_fake_success_with_one_insert(self):
        for index in range(450):
            method, path = (
                ("GET", "/feedback"), ("POST", "/feedback"),
                ("PUT", "/submit"), ("PATCH", "/submit"), ("DELETE", "/submit"),
            )[index % 5]
            response = self.request(path, method)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), {"ok": True, "message": "提交成功"})
        self.assertEqual(self.insert.call_count, 1)
        self.assertEqual(self.execute.call_count, 1)
        self.route.assert_not_called()

    def test_repeated_page_requests_keep_404_with_one_insert(self):
        for index in range(450):
            response = self.request(
                f"/page-{index}", headers={"User-Agent": f"browser-{index}"},
            )
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.data, b"Not Found")
        self.assertEqual(self.insert.call_count, 1)
        self.assertEqual(self.execute.call_count, 1)
        self.route.assert_not_called()

    def test_distinct_blocked_reasons_have_separate_windows(self):
        for _ in range(20):
            self.request("/admin")
            self.request("/feedback", "POST")
            self.request("/page")
        self.assertEqual(self.insert.call_count, 3)
        self.assertEqual(self.execute.call_count, 3)

    def test_repeated_forwarded_blocked_ips_are_deduplicated(self):
        for forwarding_headers in (
            {"CF-Connecting-IP": self.BLOCKED_IP},
            {"X-Forwarded-For": f"{self.BLOCKED_IP}, 192.0.2.10"},
        ):
            with self.subTest(headers=forwarding_headers):
                security._recent_log_keys.clear()
                self.db.reset_mock()
                for _ in range(20):
                    response = self.request(
                        "/admin", ip="192.0.2.10",
                        headers={**self.HEADERS, **forwarding_headers},
                    )
                    self.assertEqual(response.status_code, 403)
                self.assertEqual(self.insert.call_count, 1)
                self.assertEqual(self.execute.call_count, 1)
                self.assertEqual(self.insert.call_args.args[0]["ip"], self.BLOCKED_IP)
        self.route.assert_not_called()

    def test_next_insert_is_allowed_at_window_expiry(self):
        self.request("/admin")
        self.clock.return_value = 1299.999
        self.request("/admin")
        self.assertEqual(self.execute.call_count, 1)
        self.clock.return_value = 1300.0
        self.request("/admin")
        self.request("/admin")
        self.assertEqual(self.execute.call_count, 2)

    def test_failed_inserts_are_throttled_and_do_not_change_response(self):
        self.execute.side_effect = RuntimeError("Supabase unavailable")
        for _ in range(50):
            response = self.request("/admin")
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.get_json(), {"error": "Forbidden"})
        self.assertEqual(self.execute.call_count, 1)
        self.clock.return_value = 1300.0
        self.request("/admin")
        self.assertEqual(self.execute.call_count, 2)
        self.route.assert_not_called()

    def test_nonpositive_configuration_retains_a_one_second_window(self):
        for interval in (0, -5):
            with self.subTest(interval=interval), patch("security.LOG_DEDUP_SECONDS", interval):
                security._recent_log_keys.clear()
                self.db.reset_mock()
                self.clock.return_value = 1000.0
                for _ in range(20):
                    self.assertEqual(self.request("/admin").status_code, 403)
                self.clock.return_value = 1000.999
                self.request("/admin")
                self.assertEqual(self.execute.call_count, 1)
                self.clock.return_value = 1001.0
                self.request("/admin")
                self.assertEqual(self.execute.call_count, 2)

    def test_concurrent_blocked_requests_share_one_audit_reservation(self):
        start = Barrier(16)

        def send_request(_):
            start.wait(timeout=5)
            with self.app.test_client() as client:
                return self.request("/admin", client=client).status_code

        with ThreadPoolExecutor(max_workers=16) as pool:
            statuses = list(pool.map(send_request, range(64)))
        self.assertEqual(statuses, [403] * 64)
        self.assertEqual(self.insert.call_count, 1)
        self.assertEqual(self.execute.call_count, 1)
        self.route.assert_not_called()

    def test_nonblocked_events_remain_deduplicated(self):
        for _ in range(20):
            response = self.request("/page", ip="192.0.2.1", headers={"User-Agent": ""})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"business response")
        self.execute.assert_called_once()
        self.assertFalse(self.insert.call_args.args[0]["blocked"])
        self.assertEqual(self.route.call_count, 20)

    def test_other_blocked_event_types_are_also_deduplicated(self):
        for ip, path, headers, kwargs, status in (
            ("192.0.2.1", "/admin", {"User-Agent": ""}, {}, 403),
            ("192.0.2.2", "/page", {"User-Agent": "curl/8.0"}, {}, 403),
            ("192.0.2.3", "/feedback", self.HEADERS, {"json": {"text": "test-abuse"}}, 200),
        ):
            with self.subTest(ip=ip):
                for _ in range(20):
                    response = self.request(path, "POST", ip=ip, headers=headers, **kwargs)
                    self.assertEqual(response.status_code, status)
        self.assertEqual(self.execute.call_count, 3)
        self.route.assert_not_called()

    def test_excluded_and_trusted_requests_still_skip_auditing(self):
        self.assertEqual(self.request("/health").get_json(), {"status": "ok"})
        self.assertEqual(
            self.request("/page", headers={"User-Agent": "PVZH-KeepAlive/1.0"}).status_code,
            200,
        )
        with patch("security.TRUSTED_IPS", {self.BLOCKED_IP}):
            self.assertEqual(self.request("/page").status_code, 200)
        self.execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
