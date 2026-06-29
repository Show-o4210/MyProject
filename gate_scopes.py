# gate_scopes.py
"""邀请码权限分区：辅助 / Mod / 完全通行；下载中心不门禁。"""

from datetime import datetime, timedelta, timezone

TOKEN_SCOPES = frozenset({"full", "aux", "mod"})

SCOPE_LABELS = {
    "full": "完全通行",
    "aux": "辅助工具",
    "mod": "Mod 工具",
}

AUDIENCE_HINTS = {
    "full": "辅助 + Mod 均可使用",
    "aux": "建议发给普通用户（刷卡/卡包/卡组等）",
    "mod": "建议发给 Modder（解包/幻影/关卡编辑等）",
}

TZ_CN = timezone(timedelta(hours=8))

# 永远不需要邀请码的路径前缀
GATE_OPEN_PREFIXES = (
    "/api/download/",
)

GATE_OPEN_EXACT = {
    "/api/gate/verify",
    "/api/gate/status",
    "/api/gate/logout",
    "/api/phantom/ping",
    "/health",
}

# 辅助工具区 API（对应首页 aux Tab）
AUX_API_PREFIXES = (
    "/api/send-cards",
    "/api/generate-diamonds",
    "/api/init_data",
    "/api/quick_export",
    "/api/eadp/",
    "/api/packs",
    "/api/pack-settings",
    "/api/buy-pack",
    "/api/feedback/",
)

# Mod 工具区 API（对应首页 mod Tab）
MOD_API_PREFIXES = (
    "/api/editor/",
    "/api/phantom/",
)

MOD_EXACT_PATHS = {
    "/unpack",
    "/repack",
    "/unity/inspect",
    "/unity/validate-repack",
}


def normalize_scope(value: str | None, default: str = "full") -> str:
    scope = (value or default).strip().lower()
    if scope not in TOKEN_SCOPES:
        raise ValueError(f"无效 scope: {value}")
    return scope


def scope_capabilities(token_scope: str) -> dict[str, bool]:
    scope = normalize_scope(token_scope)
    return {
        "can_full": scope == "full",
        "can_aux": scope in {"full", "aux"},
        "can_mod": scope in {"full", "mod"},
    }


def scope_grants_access(token_scope: str, required_scope: str | None) -> bool:
    if required_scope is None:
        return True
    scope = normalize_scope(token_scope)
    if scope == "full":
        return True
    return scope == required_scope


def get_path_required_scope(path: str, method: str) -> str | None:
    """返回 None 表示无需门禁；否则为 aux / mod。"""
    if path in GATE_OPEN_EXACT:
        return None
    if any(path.startswith(prefix) for prefix in GATE_OPEN_PREFIXES):
        return None

    if any(path.startswith(prefix) for prefix in AUX_API_PREFIXES):
        return "aux"
    if any(path.startswith(prefix) for prefix in MOD_API_PREFIXES):
        return "mod"
    if method.upper() != "GET" and path in MOD_EXACT_PATHS:
        return "mod"

    return None


def is_protected_request(path: str, method: str) -> bool:
    return get_path_required_scope(path, method) is not None


def build_expires_at_from_mdh(month: int, day: int, hour: int) -> str:
    now = datetime.now(TZ_CN)
    year = now.year
    candidate = datetime(year, month, day, hour, 0, 0, tzinfo=TZ_CN)
    if candidate <= now:
        candidate = datetime(year + 1, month, day, hour, 0, 0, tzinfo=TZ_CN)
    return candidate.astimezone(timezone.utc).isoformat()


def build_expires_at_from_days(days: int) -> str:
    if days < 1:
        raise ValueError("days 必须 >= 1")
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def resolve_expires_at(data: dict) -> str | None:
    """解析管理端提交的过期时间配置。"""
    if data.get("expires_at"):
        return str(data["expires_at"])

    if data.get("expires_in_days") is not None:
        return build_expires_at_from_days(int(data["expires_in_days"]))

    mdh = data.get("expires_mdh")
    if isinstance(mdh, dict):
        month = int(mdh["month"])
        day = int(mdh["day"])
        hour = int(mdh["hour"])
        if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23):
            raise ValueError("月日时范围无效")
        return build_expires_at_from_mdh(month, day, hour)

    return None