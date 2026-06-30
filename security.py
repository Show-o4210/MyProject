# security.py
from flask import request, jsonify, make_response
from database import supabase
import datetime
import os
import re

"""
网站安全拦截模块

接入方式：
    from security import init_security_handlers
    init_security_handlers(app)

设计原则：
1. 对明确恶意 IP 直接封禁。
2. 不再把 Edg/148.0.0.0 当成恶意特征，因为这可能误伤正常浏览器。
3. 对留言/反馈等提交类接口采用“影子封禁”：返回成功，但实际不进入业务逻辑。
4. 对后台、统计、上传等敏感接口硬拦截。
5. 所有命中都写入 security_logs，方便你后续取证。
"""

# =========================
# 基础配置
# =========================

# 明确封禁 IP：本次辱骂留言来源
# 也可以在环境变量中追加：SECURITY_BLOCKED_IPS="1.1.1.1,2.2.2.2"
DEFAULT_BLOCKED_IPS = {
    "60.27.42.212",
}

# 额外封禁 IP，方便上线后不改代码直接在 Render 环境变量里调整
EXTRA_BLOCKED_IPS = {
    ip.strip()
    for ip in os.getenv("SECURITY_BLOCKED_IPS", "").split(",")
    if ip.strip()
}

BLOCKED_IPS = DEFAULT_BLOCKED_IPS | EXTRA_BLOCKED_IPS

# 提交类接口：命中封禁时返回“假成功”，避免对方知道自己被拦截
# 你可以按实际蓝图路径继续补充
SHADOW_BAN_PATH_KEYWORDS = [
    "/feedback",
    "/message",
    "/comment",
    "/api/feedback",
    "/api/message",
    "/api/comment",
]

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
}

# 可选：内容辱骂词/垃圾词检测。
# 不建议写太宽，否则会误杀正常留言。
ABUSE_TEXT_PATTERNS = [
    # r"辱骂关键词1",
    # r"辱骂关键词2",
]

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


def get_visitor_info():
    """
    获取访问者 IP 与 UA。

    优先级：
    1. CF-Connecting-IP：如果你套了 Cloudflare，这是最有价值的真实访客 IP。
    2. X-Forwarded-For：常见代理头，但可被伪造，取第一个。
    3. request.remote_addr：Flask 看到的直接连接来源。
    """
    cf_ip = request.headers.get("CF-Connecting-IP", "").strip()
    x_forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
    remote_addr = request.remote_addr or "unknown"

    if cf_ip:
        ip = cf_ip
    elif x_forwarded_for:
        ip = x_forwarded_for.split(",")[0].strip()
    else:
        ip = remote_addr

    user_agent = request.headers.get("User-Agent", "") or ""
    return ip, user_agent


def detect_suspicious_ua(user_agent):
    """UA 只作为辅助检测，不作为单独封禁依据。"""
    for key, config in SUSPICIOUS_UA_PATTERNS.items():
        if re.search(config["pattern"], user_agent, re.IGNORECASE):
            return key, config
    return None, None


def get_request_text_sample(max_len=500):
    """
    尝试提取提交内容样本，用于日志与辱骂检测。
    注意：这里只取短样本，避免日志过大。
    """
    try:
        if request.is_json:
            payload = request.get_json(silent=True) or {}
            text = str(payload)
        else:
            text = " ".join([str(v) for v in request.form.values()])
        return text[:max_len]
    except Exception:
        return ""


def contains_abuse_text(text):
    if not text:
        return False
    for pattern in ABUSE_TEXT_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def log_security_event(ip, user_agent, reason, severity="medium", blocked=True):
    """记录安全事件到 Supabase。表不存在或字段不匹配时只打印，不影响网站运行。"""
    try:
        data = {
            "ip": ip,
            "user_agent": user_agent,
            "reason": reason,
            "severity": severity,
            "request_path": request.path,
            "request_method": request.method,
            "timestamp": utc_now_iso(),
            "blocked": blocked,
        }
        result = supabase.table("security_logs").insert(data).execute()
        print(f"[SECURITY] {'BLOCKED' if blocked else 'LOGGED'} {ip} {request.method} {request.path} - {reason}")
        return result
    except Exception as e:
        print(f"[SECURITY] Failed to log to Supabase: {e}")
        print(f"[SECURITY] Event fallback: ip={ip}, method={request.method}, path={request.path}, reason={reason}")
        return None


def fake_success_response():
    """
    影子封禁响应：让对方以为提交成功。
    前端如果期望 ok:true，这里通常不会报错。
    """
    return make_response(jsonify({
        "ok": True,
        "message": "submitted"
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

    # 1. 明确封禁 IP：本次事件首要策略
    if ip in BLOCKED_IPS:
        reason = "blocked_ip: known abusive visitor"

        # 敏感接口：直接硬拒绝
        if path_matches(path, SENSITIVE_PATH_KEYWORDS):
            log_security_event(ip, user_agent, reason, severity="high", blocked=True)
            return forbidden_response()

        # 提交类接口：影子封禁，返回假成功，不进入后续业务逻辑
        if method in {"POST", "PUT", "PATCH", "DELETE"} or path_matches(path, SHADOW_BAN_PATH_KEYWORDS):
            log_security_event(ip, user_agent, reason + " / shadow_banned", severity="high", blocked=True)
            return fake_success_response()

        # 其他普通页面：伪装 404
        log_security_event(ip, user_agent, reason + " / hidden_404", severity="high", blocked=True)
        return not_found_response()

    # 2. 辅助记录：脚本 UA / 空 UA，不直接封
    ua_key, ua_config = detect_suspicious_ua(user_agent)
    if ua_config:
        # 对敏感接口提高强度
        if path_matches(path, SENSITIVE_PATH_KEYWORDS):
            log_security_event(ip, user_agent, ua_config["description"], severity=ua_config["severity"], blocked=True)
            return forbidden_response()
        else:
            log_security_event(ip, user_agent, ua_config["description"], severity=ua_config["severity"], blocked=False)

    # 3. 内容辱骂检测：只对提交类请求检查
    if method in {"POST", "PUT", "PATCH"} and path_matches(path, SHADOW_BAN_PATH_KEYWORDS):
        text_sample = get_request_text_sample()
        if contains_abuse_text(text_sample):
            log_security_event(ip, user_agent, "abusive_text_detected", severity="high", blocked=True)
            return fake_success_response()

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
        """
        admin_token = os.getenv("SECURITY_ADMIN_TOKEN", "")
        request_token = request.headers.get("X-Admin-Token", "")

        if not admin_token or request_token != admin_token:
            return jsonify({"error": "Forbidden"}), 403

        try:
            today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
            result = supabase.table("security_logs") \
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
            print(f"[SECURITY] stats error: {e}")
            return jsonify({"error": "stats unavailable"}), 500
