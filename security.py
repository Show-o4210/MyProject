"""Small, shared request budgets for a single-worker read-only service."""
import ipaddress
import math
import threading
import time

from flask import current_app, jsonify, request
from limits import parse_many
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter


def normalize_ip(value):
    if not isinstance(value, str) or not value or len(value) > 64 or "%" in value:
        return None
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def client_ip():
    # Enable only behind an ingress that overwrites this header. Never read XFF.
    if current_app.config["TRUST_CLOUDFLARE_CLIENT_IP"]:
        forwarded = normalize_ip(request.headers.get("CF-Connecting-IP"))
        if forwarded:
            return forwarded
    return normalize_ip(request.remote_addr) or "unknown"


def init_request_protection(app):
    ip_rules = parse_many(app.config["REQUEST_LIMIT_PER_IP"])
    global_rules = parse_many(app.config["REQUEST_LIMIT_GLOBAL"])
    if not ip_rules or not global_rules:
        raise ValueError("Both request budgets must be configured")
    storage = MemoryStorage()
    limiter = MovingWindowRateLimiter(storage)
    # Keep the entire admission decision atomic across Gunicorn's four threads.
    lock = threading.Lock()
    app.extensions["request_protection"] = {"storage": storage, "limiter": limiter}

    def limited(rule, scope, key):
        window = limiter.get_window_stats(rule, "pvzh-version", scope, key)
        retry_after = max(1, math.ceil(window.reset_time - time.time()))
        response = jsonify({
            "error": "请求过于频繁，请稍后重试。", "code": "RATE_LIMITED",
            "retry_after": retry_after,
        })
        response.status_code = 429
        response.headers["Retry-After"] = str(retry_after)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Expose-Headers"] = "Retry-After"
        return response

    @app.before_request
    def enforce_budgets():
        # A tiny, exact endpoint exemption keeps platform health checks reliable.
        if request.endpoint == "health" and request.method in {"GET", "HEAD"}:
            return None
        # Global admission comes first, so rotating client identities cannot
        # allocate unbounded per-IP buckets or bypass the service-wide budget.
        with lock:
            for rule in global_rules:
                if not limiter.test(rule, "pvzh-version", "service", "all"):
                    return limited(rule, "service", "all")
            key = client_ip()
            for rule in ip_rules:
                if not limiter.hit(rule, "pvzh-version", "client", key):
                    return limited(rule, "client", key)
            # Rejected per-IP traffic must not drain the shared global budget.
            for rule in global_rules:
                if not limiter.hit(rule, "pvzh-version", "service", "all"):
                    return limited(rule, "service", "all")
        return None
