import hashlib
import logging
import secrets
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session

from auth_gate import (
    SESSION_TOKEN_KEY,
    bind_gate_session,
    clear_gate_session,
    get_gate_status_payload,
    token_row_allows_activation,
)
from gate_scopes import SCOPE_LABELS, normalize_scope
from database import get_supabase_admin
from extensions import limiter

gate_bp = Blueprint("gate", __name__)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@gate_bp.route("/api/gate/status", methods=["GET"])
def gate_status():
    return jsonify(get_gate_status_payload())


@gate_bp.route("/api/gate/verify", methods=["POST"])
@limiter.limit("10 per minute")
def gate_verify():
    data = request.get_json(silent=True) or {}
    raw_token = str(data.get("token", "")).strip()

    if not raw_token:
        return jsonify({"error": "请输入邀请码"}), 400
    if len(raw_token) > 128:
        return jsonify({"error": "邀请码格式无效"}), 400

    token_hash = _hash_token(raw_token)

    try:
        result = (
            get_supabase_admin()
            .table("access_tokens")
            .select("id, scope, max_uses, use_count, expires_at, is_active")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return jsonify({"error": "邀请码无效"}), 401

        row = rows[0]
        already_bound = str(session.get(SESSION_TOKEN_KEY) or "") == str(row["id"])

        if not already_bound and not token_row_allows_activation(row):
            return jsonify({"error": "邀请码已过期或已达使用上限"}), 401

        # 仅绑定新邀请码时计次；同码重复验证（路由切换后）不扣次数
        if not already_bound:
            new_count = (row.get("use_count") or 0) + 1
            get_supabase_admin().table("access_tokens").update({
                "use_count": new_count,
                "last_used_at": _utc_now_iso(),
            }).eq("id", row["id"]).execute()
            row["use_count"] = new_count
        else:
            get_supabase_admin().table("access_tokens").update({
                "last_used_at": _utc_now_iso(),
            }).eq("id", row["id"]).execute()

        bind_gate_session(row)
        scope = str(row.get("scope") or "full")
        from gate_scopes import scope_capabilities

        caps = scope_capabilities(scope)
        return jsonify({
            "message": "验证成功",
            "status": "success",
            "scope": scope,
            "scope_label": SCOPE_LABELS.get(scope, scope),
            "authenticated": True,
            **caps,
        })
    except Exception as e:
        logging.error(f"邀请码验证失败: {e}")
        return jsonify({"error": "验证服务暂不可用"}), 500


@gate_bp.route("/api/gate/logout", methods=["POST"])
def gate_logout():
    clear_gate_session()
    return jsonify({"message": "已退出", "clear_local": True})


def generate_access_token() -> str:
    """供管理端创建邀请码时调用。"""
    return secrets.token_urlsafe(24)