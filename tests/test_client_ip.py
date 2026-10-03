"""Render 客户端 IP 的入口、实际限流、安全响应和归属回归；无外部写入。"""

import unittest
from unittest.mock import Mock, patch

from flask import Flask

from extensions import init_limiter, limiter
import security


class ClientIpTests(unittest.TestCase):
    PEER = "192.0.2.10"
    BLOCKED = "60.27.42.212"
    TRUSTED = "198.51.100.20"

    def setUp(self):
        security._recent_log_keys.clear()
        self.addCleanup(security._recent_log_keys.clear)
        self.audit = Mock()
        self.db = Mock()
        self.db.table.side_effect = {"security_logs": self.audit}.__getitem__
        for target, value in (
            ("security.get_supabase", Mock(return_value=self.db)),
            ("security.BLOCKED_IPS", {self.BLOCKED}),
            ("security.TRUSTED_IPS", {self.TRUSTED}),
            ("security.SELF_PING_TOKEN", ""),
            ("security.LOG_DEDUP_SECONDS", 300),
            ("builtins.print", Mock()),
        ):
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.app = Flask(__name__)
        self.app.testing = True
        self.app.config["MAX_CONTENT_LENGTH"] = 150 * 1024 * 1024
        security.init_security_handlers(self.app)
        init_limiter(self.app)
        limiter.reset()
        self.addCleanup(limiter.reset)

        @self.app.route("/identity")
        @limiter.limit("2 per hour")
        def identity():
            ip, _ = security.get_visitor_info()
            return {"ip": ip, "key": security.visitor_ip_key()}

        self.app.add_url_rule("/admin/probe", "admin_probe", lambda: "business")
        self.app.add_url_rule("/page", "page", lambda: "business")
        self.client = self.app.test_client()

    def send(self, path="/identity", headers=None, peer=PEER, **kwargs):
        return self.client.open(
            path, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json", **(headers or {})},
            environ_overrides={"REMOTE_ADDR": peer}, **kwargs,
        )

    def test_cf_ipv4_overrides_proxy_and_xff(self):
        response = self.send(headers={
            "CF-Connecting-IP": " 203.0.113.7 ", "X-Forwarded-For": self.TRUSTED,
        })
        self.assertEqual(response.get_json(), {"ip": "203.0.113.7", "key": "203.0.113.7"})

    def test_cf_ipv6_is_normalized(self):
        response = self.send(headers={"CF-Connecting-IP": "2001:0DB8:0000:0000:0000:0000:0000:0007"})
        self.assertEqual(response.get_json(), {"ip": "2001:db8::7", "key": "2001:db8::7"})

    def test_missing_cf_ignores_forged_xff(self):
        response = self.send(headers={"X-Forwarded-For": "203.0.113.7, 198.51.100.1"})
        self.assertEqual(response.get_json(), {"ip": self.PEER, "key": self.PEER})

    def test_invalid_cf_falls_back_without_500(self):
        for value in ("", " ", "garbage", "203.0.113.7, 198.51.100.1",
                      "[2001:db8::1]", "203.0.113.1:80", "fe80::1%eth0"):
            with self.subTest(value=value):
                limiter.reset()
                response = self.send(headers={"CF-Connecting-IP": value, "X-Forwarded-For": self.TRUSTED})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"ip": self.PEER, "key": self.PEER})

    def test_remote_ipv6_is_normalized(self):
        response = self.send(peer="2001:0DB8:0:0:0:0:0:8", headers={"CF-Connecting-IP": "invalid"})
        self.assertEqual(response.get_json(), {"ip": "2001:db8::8", "key": "2001:db8::8"})

    def test_invalid_or_missing_remote_uses_stable_unknown(self):
        for peer in (None, "invalid", "203.0.113.1, 192.0.2.1"):
            with self.subTest(peer=peer):
                limiter.reset()
                response = self.send(peer=peer, headers={"X-Forwarded-For": self.TRUSTED})
                self.assertEqual(response.get_json(), {"ip": "unknown", "key": "unknown"})

    def test_changing_xff_cannot_get_new_limiter_buckets(self):
        statuses = [self.send(headers={"X-Forwarded-For": f"203.0.113.{n}"}).status_code
                    for n in range(1, 5)]
        self.assertEqual(statuses, [200, 200, 429, 429])

    def test_render_cf_clients_have_independent_limiter_buckets(self):
        for ip in ("203.0.113.1", "203.0.113.2"):
            statuses = [self.send(headers={"CF-Connecting-IP": ip}).status_code for _ in range(3)]
            self.assertEqual(statuses, [200, 200, 429])

    def test_ipv6_spellings_share_limiter_bucket(self):
        values = ("2001:0DB8:0:0:0:0:0:9", "2001:db8::9", "2001:DB8::9")
        self.assertEqual([self.send(headers={"CF-Connecting-IP": v}).status_code for v in values],
                         [200, 200, 429])

    def test_ipv4_mapped_ipv6_shares_limiter_bucket(self):
        values = ("203.0.113.9", "::ffff:203.0.113.9", "::FFFF:cb00:7109")
        self.assertEqual([self.send(headers={"CF-Connecting-IP": v}).status_code for v in values],
                         [200, 200, 429])

    def test_changing_xff_cannot_escape_block_or_audit_dedup(self):
        for n in range(20):
            response = self.send("/admin/probe", peer=self.BLOCKED,
                                 headers={"X-Forwarded-For": f"203.0.113.{n}, {self.TRUSTED}"})
            self.assertEqual(response.status_code, 403)
        self.audit.insert.assert_called_once()
        self.audit.insert.return_value.execute.assert_called_once()
        self.assertEqual(self.audit.insert.call_args.args[0]["ip"], self.BLOCKED)

    def test_xff_cannot_impersonate_trusted_ip(self):
        response = self.send("/admin/probe", headers={
            "User-Agent": "curl/8.0", "X-Forwarded-For": self.TRUSTED,
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.audit.insert.call_args.args[0]["ip"], self.PEER)

    def test_xff_cannot_impersonate_blocked_ip(self):
        response = self.send(headers={"X-Forwarded-For": self.BLOCKED})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["ip"], self.PEER)
        self.audit.insert.assert_not_called()

    def test_invalid_cf_cannot_bypass_block_and_dedup(self):
        for value in ("", "invalid", f"{self.TRUSTED}, {self.BLOCKED}"):
            response = self.send("/admin/probe", peer=self.BLOCKED,
                                 headers={"CF-Connecting-IP": value, "X-Forwarded-For": self.TRUSTED})
            self.assertEqual(response.status_code, 403)
        self.audit.insert.assert_called_once()
        self.assertEqual(self.audit.insert.call_args.args[0]["ip"], self.BLOCKED)

    def test_cf_blocked_response_variants_and_dedup_remain(self):
        for path, method, status in (("/admin/probe", "GET", 403),
                                     ("/page", "POST", 200), ("/page", "GET", 404)):
            for _ in range(5):
                response = self.send(path, method=method, headers={
                    "CF-Connecting-IP": self.BLOCKED, "X-Forwarded-For": self.TRUSTED,
                })
                self.assertEqual(response.status_code, status)
                if method == "POST":
                    self.assertEqual(response.get_json(), {"ok": True, "message": "提交成功"})
        self.assertEqual(self.audit.insert.call_count, 3)  # 三个 reason 各自去重

    def test_configured_ipv6_block_uses_same_canonical_form(self):
        configured = security.parse_ip_list("2001:0DB8:0:0:0:0:0:7,invalid, ::ffff:60.27.42.212")
        self.assertEqual(configured, {"2001:db8::7", self.BLOCKED})
        with patch("security.BLOCKED_IPS", configured):
            for value in ("2001:db8::7", "2001:DB8:0:0:0:0:0:7"):
                self.assertEqual(self.send("/page", headers={"CF-Connecting-IP": value}).status_code, 404)
        self.audit.insert.assert_called_once()

    def test_configured_trusted_ipv6_uses_canonical_cf_identity(self):
        with patch("security.TRUSTED_IPS", security.parse_ip_list("2001:0DB8:0:0:0:0:0:7")):
            response = self.send("/admin/probe", headers={
                "CF-Connecting-IP": "2001:db8::7", "User-Agent": "curl/8.0",
            })
        self.assertEqual(response.status_code, 200)
        self.audit.insert.assert_not_called()

    def test_identity_and_audit_store_same_canonical_ip(self):
        response = self.send("/identity",
                             headers={"User-Agent": "", "CF-Connecting-IP": "2001:0DB8:0:0:0:0:0:7",
                                      "X-Forwarded-For": self.TRUSTED})
        self.assertEqual(response.status_code, 200)
        self.audit.insert.assert_called_once()  # 空 UA 只记录，不阻止正常请求
        self.assertEqual(response.get_json()["ip"], "2001:db8::7")
        self.assertEqual(self.audit.insert.call_args.args[0]["ip"], "2001:db8::7")
        self.assertFalse(self.audit.insert.call_args.args[0]["blocked"])


if __name__ == "__main__":
    unittest.main()
