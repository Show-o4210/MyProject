# security.py
from flask import request, jsonify, make_response
from database import get_supabase
import datetime
import ipaddress
import os
import re
import threading
import time

"""
网站安全拦截模块

接入方式：
    from security import init_security_handlers
    init_security_handlers(app)

设计原则：
1. 对明确恶意 IP 直接封禁。
2. 不再把 Edg/148.0.0.0 当成恶意特征，因为这可能误伤正常浏览器。
3. 对提交类请求采用“影子封禁”：返回成功，但实际不进入业务逻辑。
4. 对后台、统计、上传等敏感接口硬拦截。
5. 命中写入 security_logs，同一 IP+reason 按时间窗口去重，方便取证并限制写入。
6. 进程内自唤醒（KeepAlive）不得被当成外部脚本攻击。
"""

# =========================
# 基础配置
# =========================

def normalize_ip(value):
    """只接受单个 IPv4/IPv6；统一文本表示，不接受作用域、端口或地址链。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or "%" in value:
        return None
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return None
    # IPv4 的 mapped IPv6 表示也必须命中相同的名单和限流桶。
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return str(address)


def parse_ip_list(value):
    """环境变量名单与请求使用同一规范；忽略无效地址。"""
    return {ip for item in value.split(",") if (ip := normalize_ip(item)) is not None}


# 明确封禁 IP：本次辱骂留言来源
# 也可以在环境变量中追加：SECURITY_BLOCKED_IPS="1.1.1.1,2.2.2.2"
DEFAULT_BLOCKED_IPS = {
    "60.27.42.212",
    "38.180.145.148"
}

# 额外封禁 IP，方便上线后不改代码直接在 Render 环境变量里调整
EXTRA_BLOCKED_IPS = parse_ip_list(os.getenv("SECURITY_BLOCKED_IPS", ""))

BLOCKED_IPS = DEFAULT_BLOCKED_IPS | EXTRA_BLOCKED_IPS

# 可信 IP（不参与脚本 UA 告警 / 不封禁）：可选
# 例：Render 出站自唤醒 IP 曾是 74.220.49.7，但云厂商 IP 会变，优先靠 UA/Token
TRUSTED_IPS = parse_ip_list(os.getenv("SECURITY_TRUSTED_IPS", ""))

# 与 app.py keep_awake 约定一致
SELF_PING_UA_PREFIX = "PVZH-KeepAlive/"
SELF_PING_TOKEN = os.getenv("SELF_PING_TOKEN", "").strip()

# 敏感接口：命中封禁时直接拒绝
SENSITIVE_PATH_KEYWORDS = [
    "/admin",
    "/security",
    "/upload",
    "/manage",
    "/dashboard",
]

# 不参与安全检查的路径
EXCLUDED_PATH_PREFIXES = [
    "/static",
]

EXCLUDED_EXACT_PATHS = {
    "/health",
    "/favicon.ico",
    "/robots.txt",
    "/sitemap.xml",
    "/version",
    "/version.txt",
    "/api/version",
    "/sponsors",
    "/sponsors.txt",
    "/api/sponsors",
    "/thanks",
    "/thanks.txt",
    "/api/thanks",
}

# 可选：UA 异常规则。只做辅助加分/记录，不单独作为封禁依据。
SUSPICIOUS_UA_PATTERNS = {
    "empty_user_agent": {
        "pattern": r"^$",
        "description": "空 User-Agent",
        "severity": "medium",
    },
    "python_requests": {
        "pattern": r"python-requests|curl|wget|httpx|aiohttp",
        "description": "脚本/命令行请求 UA",
        "severity": "medium",
    },
}

# 所有事件按同一 IP+reason 限制写入间隔（秒，至少 1 秒），包括拦截事件
LOG_DEDUP_SECONDS = int(os.getenv("SECURITY_LOG_DEDUP_SECONDS", "300"))
_recent_log_keys: dict[str, float] = {}
_recent_log_lock = threading.Lock()

# Supabase 权限失败时降噪：连续失败时降低打印频率
_supabase_log_fail_count = 0
_supabase_log_last_warn = 0.0


# =========================
# 工具函数
# =========================

def utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def path_matches(path, keywords):
    path = path.lower()
    return any(keyword.lower() in path for keyword in keywords)


def is_excluded_path(path):
    if path in EXCLUDED_EXACT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in EXCLUDED_PATH_PREFIXES)


def resolve_client_ip():
    """
    当前 Render public Web Service 的唯一客户端 IP 规则。
    公网入口经 Cloudflare 写入 CF-Connecting-IP；部署信任边界见 docs/deployment.md。
    无效/缺失时只降级到直接连接地址，绝不采用客户端可保留的 X-Forwarded-For。
    """
    return (
        normalize_ip(request.headers.get("CF-Connecting-IP"))
        or normalize_ip(request.remote_addr)
        or "unknown"
    )


def get_visitor_info():
    """安全检查和审计共用的规范 IP 与 UA。"""
    user_agent = request.headers.get("User-Agent", "") or ""
    return resolve_client_ip(), user_agent


def visitor_ip_key():
    """Flask-Limiter 与安全检查和审计共用同一个规范 IP。"""
    return resolve_client_ip()


def is_self_ping_request(user_agent: str) -> bool:
    """
    识别进程内自唤醒请求。

    判定（任一即可）：
    1. UA 以 PVZH-KeepAlive/ 开头（app.py 默认）
    2. Header X-Self-Ping-Token 与环境变量 SELF_PING_TOKEN 一致（可选加固）
    """
    if user_agent and user_agent.startswith(SELF_PING_UA_PREFIX):
        return True
    if SELF_PING_TOKEN:
        token = request.headers.get("X-Self-Ping-Token", "").strip()
        if token and token == SELF_PING_TOKEN:
            return True
    return False


def detect_suspicious_ua(user_agent):
    """UA 只作为辅助检测，不作为单独封禁依据。"""
    for key, config in SUSPICIOUS_UA_PATTERNS.items():
        if re.search(config["pattern"], user_agent, re.IGNORECASE):
            return key, config
    return None, None


def _should_skip_dedup_log(ip: str, reason: str) -> bool:
    """所有事件按 IP+reason 节流；原子预留窗口，失败时也不立即重试。"""
    with _recent_log_lock:
        now = time.monotonic()
        interval = max(1, LOG_DEDUP_SECONDS)
        key = f"{ip}|{reason}"
        last = _recent_log_keys.get(key)
        if last is not None and (now - last) < interval:
            return True
        _recent_log_keys[key] = now
        # 清理过期记录；Supabase 网络请求在锁外执行
        if len(_recent_log_keys) > 2000:
            cutoff = now - interval
            stale = [k for k, t in _recent_log_keys.items() if t < cutoff]
            for k in stale:
                _recent_log_keys.pop(k, None)
        return False


def _format_supabase_error(err) -> str:
    """把 postgrest/APIError 收成可读短文，便于判断是表权限还是配置问题。"""
    msg = str(err)
    # postgrest 常返回 dict 形态
    if "permission denied" in msg or "42501" in msg:
        return (
            f"{msg} | 表权限/RLS 问题：请在 Supabase SQL Editor 执行 sql/security_logs.sql；"
            "确认 SUPABASE_KEY 为 anon key 且表已 GRANT INSERT TO anon"
        )
    if "Could not find the table" in msg or "PGRST205" in msg or "does not exist" in msg:
        return f"{msg} | 表不存在：请执行 sql/security_logs.sql 建表"
    if "JWT" in msg or "Invalid API key" in msg or "401" in msg:
        return f"{msg} | Render/环境变量问题：检查 SUPABASE_URL 与 SUPABASE_KEY"
    return msg


def log_security_event(ip, user_agent, reason, severity="medium", blocked=True):
    """记录安全事件到 Supabase。表不存在或字段不匹配时只打印，不影响网站运行。"""
    global _supabase_log_fail_count, _supabase_log_last_warn

    if _should_skip_dedup_log(ip, reason):
        return None

    try:
        data = {
            "ip": ip,
            "user_agent": (user_agent or "")[:2000],
            "reason": (reason or "")[:500],
            "severity": severity if severity in {"low", "medium", "high", "critical"} else "medium",
            "request_path": (request.path or "")[:2000],
            "request_method": (request.method or "")[:16],
            "timestamp": utc_now_iso(),
            "blocked": blocked,
        }
        # anon 通常仅 GRANT INSERT；默认 returning=representation 会因无 SELECT 失败
        from postgrest.types import ReturnMethod

        result = (
            get_supabase()
            .table("security_logs")
            .insert(data, returning=ReturnMethod.minimal)
            .execute()
        )
        _supabase_log_fail_count = 0
        print(f"[SECURITY] {'BLOCKED' if blocked else 'LOGGED'} {ip} {request.method} {request.path} - {reason}")
        return result
    except Exception as e:
        _supabase_log_fail_count += 1
        now = time.time()
        # 权限错误会刷屏：前 3 次全打，之后每 10 分钟最多 1 次摘要
        should_print = (
            _supabase_log_fail_count <= 3
            or (now - _supabase_log_last_warn) >= 600
        )
        if should_print:
            _supabase_log_last_warn = now
            print(f"[SECURITY] Failed to log to Supabase: {_format_supabase_error(e)}")
            print(
                f"[SECURITY] Event fallback: ip={ip}, method={request.method}, "
                f"path={request.path}, reason={reason}, fail_count={_supabase_log_fail_count}"
            )
        return None


def fake_success_response():
    """
    影子封禁响应：让对方以为提交成功。
    返回统一的提交成功响应：{ ok: true, message: "..." }
    """
    return make_response(jsonify({
        "ok": True,
        "message": "提交成功"
    }), 200)


def forbidden_response():
    """硬封禁响应：不给具体原因，避免暴露规则。"""
    return make_response(jsonify({
        "error": "Forbidden"
    }), 403)


def not_found_response():
    """普通页面封禁时伪装成不存在，减少对方调试价值。"""
    return make_response("Not Found", 404)


# =========================
# 核心安全检查
# =========================

def security_check():
    ip, user_agent = get_visitor_info()
    path = request.path
    method = request.method.upper()

    # 0. 自唤醒 / 可信 IP：跳过后续检查，避免把 Render 出站保活当成攻击
    if is_self_ping_request(user_agent) or ip in TRUSTED_IPS:
        return None

    # 1. 明确封禁 IP：本次事件首要策略
    if ip in BLOCKED_IPS:
        reason = "blocked_ip: known abusive visitor"

        # 敏感接口：直接硬拒绝
        if path_matches(path, SENSITIVE_PATH_KEYWORDS):
            log_security_event(ip, user_agent, reason, severity="high", blocked=True)
            return forbidden_response()

        # 提交类接口：影子封禁，返回假成功，不进入后续业务逻辑
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            log_security_event(ip, user_agent, reason + " / shadow_banned", severity="high", blocked=True)
            return fake_success_response()

        # 其他普通页面：伪装 404
        log_security_event(ip, user_agent, reason + " / hidden_404", severity="high", blocked=True)
        return not_found_response()

    # 2. 脚本 UA / 空 UA
    # - 敏感路径：硬拒绝
    # - 纯脚本工具（curl/wget/python-requests 等）访问业务页：直接 403，
    #   避免返回完整 HTML（浪费带宽与 CPU）；搜索引擎 UA 不在此列表内。
    # - 其余可疑 UA：仅记录（去重），不封禁
    ua_key, ua_config = detect_suspicious_ua(user_agent)
    if ua_config:
        if path_matches(path, SENSITIVE_PATH_KEYWORDS):
            log_security_event(ip, user_agent, ua_config["description"], severity=ua_config["severity"], blocked=True)
            return forbidden_response()

        # 明确的命令行/脚本客户端：业务页与 API 一律 403（健康检查已在白名单）
        if ua_key == "python_requests":
            log_security_event(
                ip, user_agent, ua_config["description"] + " / hard_block",
                severity=ua_config["severity"], blocked=True,
            )
            return forbidden_response()

        # 空 UA 等：仅记录
        log_security_event(ip, user_agent, ua_config["description"], severity=ua_config["severity"], blocked=False)

    return None


# =========================
# Flask 接入
# =========================

def init_security_handlers(app):
    """初始化全局安全处理。"""

    @app.before_request
    def before_request_security_check():
        if is_excluded_path(request.path):
            return None

        result = security_check()
        if result:
            return result

        return None

    @app.route("/security/stats")
    def security_stats():
        """
        查看拦截统计。

        必须设置环境变量：
            SECURITY_ADMIN_TOKEN=你自己的随机强密码

        请求时带 Header：
            X-Admin-Token: 你自己的随机强密码

        说明：默认 sql/security_logs.sql 只给 anon INSERT。
        SELECT 需要 service_role 或你在 SQL 中按注释放开 anon SELECT。
        """
        admin_token = os.getenv("SECURITY_ADMIN_TOKEN", "")
        request_token = request.headers.get("X-Admin-Token", "")

        if not admin_token or request_token != admin_token:
            return jsonify({"error": "Forbidden"}), 403

        try:
            today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            result = get_supabase().table("security_logs") \
                .select("ip, severity, reason, request_path, request_method, timestamp, blocked", count="exact") \
                .gte("timestamp", f"{today}T00:00:00") \
                .order("timestamp", desc=True) \
                .limit(50) \
                .execute()

            rows = result.data or []
            return jsonify({
                "total_logged_today": len(rows),
                "total_blocked_today": len([r for r in rows if r.get("blocked")]),
                "unique_ips": len(set([r.get("ip") for r in rows if r.get("ip")])),
                "samples": rows[:10],
            })
        except Exception as e:
            print(f"[SECURITY] stats error: {_format_supabase_error(e)}")
            return jsonify({
                "error": "stats unavailable",
                "hint": (
                    "写入可用 anon INSERT；读取需 service_role 或在 "
                    "sql/security_logs.sql 中按注释启用 anon SELECT"
                ),
            }), 500
