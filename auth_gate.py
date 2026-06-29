# auth_gate.py
"""邀请码 API 门禁：HTML 与下载放行；辅助/Mod 按 scope 细分。"""

import hashlib
import logging
from datetime import datetime, timezone

from flask import jsonify, request, session

from config import Config
from database import get_supabase_admin
from gate_scopes import (
    SCOPE_LABELS,
    get_path_required_scope,
    is_protected_request,
    scope_capabilities,
    scope_grants_access,
)

SESSION_TOKEN_KEY = "gate_token_id"
SESSION_SCOPE_KEY = "gate_scope"
SESSION_CACHE_KEY = "gate_cache"
GATE_TOKEN_HEADER = "X-Gate-Token"
REVALIDATE_SECONDS = 300

GATE_EXCLUDED_PREFIXES = (
    "/static",
    "/admin",
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def is_gate_excluded(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in GATE_EXCLUDED_PREFIXES)


def _token_row_base_valid(row: dict | None) -> bool:
    """校验启用状态与过期时间。"""
    if not row or not row.get("is_active"):
        return False

    expires_at = _parse_iso(row.get("expires_at"))
    if expires_at and _utc_now() >= expires_at:
        return False

    return True


def token_row_allows_access(row: dict | None) -> bool:
    """已激活会话/API 请求：只看是否有效、未过期，不重复检查 use_count。"""
    return _token_row_base_valid(row)


def token_row_allows_activation(row: dict | None) -> bool:
    """首次激活 / 换设备激活：才检查使用次数上限。"""
    if not _token_row_base_valid(row):
        return False

    max_uses = row.get("max_uses")
    use_count = row.get("use_count") or 0
    if max_uses is not None and use_count >= max_uses:
        return False

    return True


def token_row_is_valid(row: dict | None) -> bool:
    return token_row_allows_access(row)


def _fetch_token_row(token_id: str) -> dict | None:
    try:
        result = (
            get_supabase_admin()
            .table("access_tokens")
            .select("id, scope, max_uses, use_count, expires_at, is_active")
            .eq("id", token_id)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.warning(f"读取邀请码失败 id={token_id}: {e}")
        return None


def _fetch_token_row_by_hash(raw_token: str) -> dict | None:
    try:
        result = (
            get_supabase_admin()
            .table("access_tokens")
            .select("id, scope, max_uses, use_count, expires_at, is_active")
            .eq("token_hash", _hash_token(raw_token))
            .limit(1)
            .execute()
        )
        rows = result.data or []
        return rows[0] if rows else None
    except Exception as e:
        logging.warning("读取邀请码失败(hash): %s", e)
        return None


def _row_from_session_cache() -> dict | None:
    cache = session.get(SESSION_CACHE_KEY)
    if not isinstance(cache, dict):
        return None

    cached_at = cache.get("cached_at")
    if not cached_at:
        return None
    try:
        cached_dt = datetime.fromisoformat(str(cached_at).replace("Z", "+00:00"))
    except ValueError:
        return None

    age = (_utc_now() - cached_dt).total_seconds()
    if age > REVALIDATE_SECONDS:
        return None

    return {
        "id": cache.get("id"),
        "scope": cache.get("scope") or "full",
        "max_uses": cache.get("max_uses"),
        "use_count": cache.get("use_count") or 0,
        "expires_at": cache.get("expires_at"),
        "is_active": cache.get("is_active", True),
    }


def bind_gate_session(row: dict) -> None:
    session.permanent = True
    session[SESSION_TOKEN_KEY] = row["id"]
    session[SESSION_SCOPE_KEY] = str(row.get("scope") or "full")
    session[SESSION_CACHE_KEY] = {
        "id": row["id"],
        "scope": str(row.get("scope") or "full"),
        "max_uses": row.get("max_uses"),
        "use_count": row.get("use_count") or 0,
        "expires_at": row.get("expires_at"),
        "is_active": row.get("is_active", True),
        "cached_at": _utc_now().isoformat(),
    }


def get_raw_gate_token_from_request() -> str:
    header = request.headers.get(GATE_TOKEN_HEADER, "").strip()
    if header:
        return header
    try:
        form_token = request.form.get("_gate_token", "").strip()
        if form_token:
            return form_token
    except Exception:
        pass
    return ""


def resolve_gate_row() -> dict | None:
    """请求头/表单 token 优先，其次 Session 缓存与查库。"""
    raw_token = get_raw_gate_token_from_request()
    if raw_token:
        row = _fetch_token_row_by_hash(raw_token)
        if token_row_allows_access(row):
            bind_gate_session(row)
            return row

    cached = _row_from_session_cache()
    if cached and token_row_allows_access(cached):
        return cached

    token_id = session.get(SESSION_TOKEN_KEY)
    if token_id:
        row = _fetch_token_row(str(token_id))
        if token_row_allows_access(row):
            bind_gate_session(row)
            return row

    return None


def get_gate_session_row() -> dict | None:
    return resolve_gate_row()


def is_gate_authenticated_for_path(path: str, method: str) -> bool:
    required_scope = get_path_required_scope(path, method)
    if required_scope is None:
        return True

    row = get_gate_session_row()
    if not row:
        return False

    return scope_grants_access(str(row.get("scope") or "full"), required_scope)


def is_gate_authenticated() -> bool:
    return get_gate_session_row() is not None


def get_gate_status_payload() -> dict:
    row = get_gate_session_row()
    if not row:
        return {
            "gate_enabled": Config.GATE_ENABLED,
            "authenticated": False,
            "scope": None,
            "scope_label": None,
            "can_aux": False,
            "can_mod": False,
        }

    scope = str(row.get("scope") or "full")
    caps = scope_capabilities(scope)
    return {
        "gate_enabled": Config.GATE_ENABLED,
        "authenticated": True,
        "scope": scope,
        "scope_label": SCOPE_LABELS.get(scope, scope),
        **caps,
    }


def clear_gate_session() -> None:
    session.pop(SESSION_TOKEN_KEY, None)
    session.pop(SESSION_SCOPE_KEY, None)
    session.pop(SESSION_CACHE_KEY, None)


def gate_denied_response():
    required_scope = get_path_required_scope(request.path, request.method)
    row = get_gate_session_row()

    if row and required_scope and not scope_grants_access(str(row.get("scope") or "full"), required_scope):
        scope_label = SCOPE_LABELS.get(required_scope, required_scope)
        return jsonify({
            "error": f"当前邀请码无「{scope_label}」权限",
            "code": "GATE_SCOPE_DENIED",
            "required_scope": required_scope,
            "current_scope": str(row.get("scope") or "full"),
            "message": f"此功能需要「{scope_label}」或「完全通行」邀请码",
        }), 403

    return jsonify({
        "error": "需要邀请码",
        "code": "GATE_REQUIRED",
        "required_scope": required_scope,
        "message": "请先在顶部导航栏点击「激活」输入邀请码",
    }), 401


def init_gate_handlers(app):
    @app.before_request
    def before_request_gate_check():
        if not Config.GATE_ENABLED:
            return None
        if is_gate_excluded(request.path):
            return None
        if not is_protected_request(request.path, request.method):
            return None
        if is_gate_authenticated_for_path(request.path, request.method):
            return None
        return gate_denied_response()