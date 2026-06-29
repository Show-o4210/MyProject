import hashlib
import logging
from functools import wraps

from flask import Blueprint, jsonify, render_template, request

from blueprints.gate import generate_access_token
from config import Config
from database import get_supabase, get_supabase_admin
from gate_scopes import AUDIENCE_HINTS, SCOPE_LABELS, normalize_scope, resolve_expires_at

admin_tokens_bp = Blueprint("admin_tokens", __name__)


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _verify_admin_jwt(jwt_token: str) -> str | None:
    try:
        response = get_supabase().auth.get_user(jwt_token)
        user = getattr(response, "user", None)
        email = getattr(user, "email", None) if user else None
        if email and email.lower() in Config.ADMIN_EMAILS:
            return email.lower()
    except Exception as e:
        logging.warning(f"管理员 JWT 校验失败: {e}")
    return None


def require_admin(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not Config.ADMIN_EMAILS:
            return jsonify({"error": "未配置 ADMIN_EMAILS"}), 503

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Unauthorized"}), 401

        email = _verify_admin_jwt(auth_header[7:].strip())
        if not email:
            return jsonify({"error": "Forbidden"}), 403

        request.admin_email = email
        return view(*args, **kwargs)

    return wrapped


def _serialize_token_row(row: dict) -> dict:
    scope = str(row.get("scope") or "full")
    return {
        "id": row.get("id"),
        "label": row.get("label"),
        "scope": scope,
        "scope_label": SCOPE_LABELS.get(scope, scope),
        "audience_hint": AUDIENCE_HINTS.get(scope, ""),
        "max_uses": row.get("max_uses"),
        "use_count": row.get("use_count", 0),
        "expires_at": row.get("expires_at"),
        "is_active": row.get("is_active", True),
        "created_by": row.get("created_by"),
        "created_at": row.get("created_at"),
        "last_used_at": row.get("last_used_at"),
    }


@admin_tokens_bp.route("/admin")
def admin_page():
    return render_template(
        "admin.html",
        supabase_url=Config.SUPABASE_URL or "",
        supabase_key=Config.SUPABASE_KEY or "",
    )


@admin_tokens_bp.route("/admin/api/tokens", methods=["GET"])
@require_admin
def list_tokens():
    try:
        result = (
            get_supabase_admin()
            .table("access_tokens")
            .select("id, label, scope, max_uses, use_count, expires_at, is_active, created_by, created_at, last_used_at")
            .order("created_at", desc=True)
            .execute()
        )
        return jsonify({"tokens": [_serialize_token_row(row) for row in (result.data or [])]})
    except Exception as e:
        logging.error(f"读取邀请码列表失败: {e}")
        return jsonify({"error": "读取失败"}), 500


@admin_tokens_bp.route("/admin/api/tokens", methods=["POST"])
@require_admin
def create_token():
    data = request.get_json(silent=True) or {}
    label = str(data.get("label", "")).strip() or None

    max_uses = data.get("max_uses")
    if max_uses is not None:
        try:
            max_uses = int(max_uses)
            if max_uses < 1:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({"error": "max_uses 必须是正整数或留空（不限）"}), 400

    try:
        scope = normalize_scope(data.get("scope"), default="full")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    try:
        expires_at = resolve_expires_at(data)
    except (TypeError, ValueError) as e:
        return jsonify({"error": f"过期时间无效: {e}"}), 400

    raw_token = generate_access_token()
    payload = {
        "token_hash": _hash_token(raw_token),
        "label": label,
        "scope": scope,
        "max_uses": max_uses,
        "use_count": 0,
        "expires_at": expires_at,
        "is_active": True,
        "created_by": request.admin_email,
    }

    try:
        result = get_supabase_admin().table("access_tokens").insert(payload).execute()
        rows = result.data or []
        created = _serialize_token_row(rows[0]) if rows else _serialize_token_row(payload)
        created["token"] = raw_token
        return jsonify({
            "message": "邀请码已创建，请立即保存，明文不会再次显示",
            "token_record": created,
        }), 201
    except Exception as e:
        logging.error(f"创建邀请码失败: {e}")
        return jsonify({"error": "创建失败，请确认 access_tokens 表已建好"}), 500


@admin_tokens_bp.route("/admin/api/tokens/<token_id>", methods=["PATCH"])
@require_admin
def update_token(token_id):
    data = request.get_json(silent=True) or {}
    updates = {}

    if "is_active" in data:
        updates["is_active"] = bool(data["is_active"])

    if "label" in data:
        label = str(data.get("label", "")).strip()
        updates["label"] = label or None

    if "max_uses" in data:
        max_uses = data.get("max_uses")
        if max_uses is None:
            updates["max_uses"] = None
        else:
            try:
                max_uses = int(max_uses)
                if max_uses < 1:
                    raise ValueError
                updates["max_uses"] = max_uses
            except (TypeError, ValueError):
                return jsonify({"error": "max_uses 必须是正整数或 null"}), 400

    if "scope" in data:
        try:
            updates["scope"] = normalize_scope(data.get("scope"))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    if any(key in data for key in ("expires_at", "expires_in_days", "expires_mdh")):
        try:
            updates["expires_at"] = resolve_expires_at(data)
        except (TypeError, ValueError) as e:
            return jsonify({"error": f"过期时间无效: {e}"}), 400

    if not updates:
        return jsonify({"error": "没有可更新字段"}), 400

    try:
        result = (
            get_supabase_admin()
            .table("access_tokens")
            .update(updates)
            .eq("id", token_id)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return jsonify({"error": "邀请码不存在"}), 404
        return jsonify({"token": _serialize_token_row(rows[0])})
    except Exception as e:
        logging.error(f"更新邀请码失败: {e}")
        return jsonify({"error": "更新失败"}), 500