from datetime import datetime

from flask import Blueprint, jsonify, request

from extensions import limiter
from logic_ea_api import (
    STORED_TOKEN_FILE,
    check_token_valid,
    ensure_valid_token,
    load_stored_credentials,
    parse_credentials_from_dat,
    refresh_access_token,
)

eadp_auth_bp = Blueprint("eadp_auth", __name__)

MAX_DAT_FILE_SIZE = 512 * 1024


def _format_expires_at(expires_at: int | None) -> str | None:
    if not expires_at:
        return None
    try:
        return datetime.fromtimestamp(int(expires_at)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return None


def _build_credential_response(credentials: dict) -> dict:
    access_token = credentials.get("access_token")
    refresh_token = credentials.get("refresh_token")
    expires_at = credentials.get("expires_at")

    if not access_token:
        return {
            "success": False,
            "error": "未在凭证文件中找到 access_token，请确认上传的是正确的 .dat 文件。",
        }

    return {
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "expires_at_text": _format_expires_at(expires_at),
        "token_valid": check_token_valid(expires_at),
        "has_refresh_token": bool(refresh_token),
    }


@eadp_auth_bp.route("/api/eadp/stored-credentials", methods=["GET"])
@limiter.limit("30 per minute")
def get_stored_credentials():
    """读取 data/token.dat 长期凭证，必要时自动续期。"""
    stored = load_stored_credentials()
    if not stored.get("success"):
        return jsonify({
            "success": False,
            "error": stored.get("error", "读取本地凭证失败"),
            "source": "data/token.dat",
        }), 404

    access_token = stored.get("access_token")
    refresh_token = stored.get("refresh_token")
    expires_at = stored.get("expires_at")
    refreshed = False

    if refresh_token and not check_token_valid(expires_at):
        access_token, refresh_token, expires_at, refreshed = ensure_valid_token(
            access_token,
            refresh_token,
            expires_at,
        )

    return jsonify({
        "success": True,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "expires_at_text": _format_expires_at(expires_at),
        "token_valid": check_token_valid(expires_at),
        "has_refresh_token": bool(refresh_token),
        "token_refreshed": refreshed,
        "source": stored.get("source", "data/token.dat"),
        "file": STORED_TOKEN_FILE,
    })


@eadp_auth_bp.route("/api/eadp/parse-dat", methods=["POST"])
@limiter.limit("20 per minute")
def parse_dat():
    """解析 nimble .dat 凭证文件，提取 Token """
    if request.content_type and "multipart/form-data" in request.content_type:
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            return jsonify({"success": False, "error": "请上传 .dat 凭证文件"}), 400

        content = uploaded.read(MAX_DAT_FILE_SIZE + 1)
        if len(content) > MAX_DAT_FILE_SIZE:
            return jsonify({"success": False, "error": "凭证文件过大（上限 512KB）"}), 400
    else:
        data = request.get_json(silent=True) or {}
        raw_content = data.get("dat_content")
        if not raw_content:
            return jsonify({"success": False, "error": "请提供 dat_content 或上传文件"}), 400

        if isinstance(raw_content, str):
            content = raw_content.encode("utf-8", errors="ignore")
        else:
            return jsonify({"success": False, "error": "dat_content 格式无效"}), 400

        if len(content) > MAX_DAT_FILE_SIZE:
            return jsonify({"success": False, "error": "凭证内容过大（上限 512KB）"}), 400

    credentials = parse_credentials_from_dat(content)
    result = _build_credential_response(credentials)
    status = 200 if result.get("success") else 400
    return jsonify(result), status


@eadp_auth_bp.route("/api/eadp/refresh-token", methods=["POST"])
@limiter.limit("10 per minute")
def refresh_token():
    """使用 refresh_token 手动或自动续期 access_token。"""
    data = request.get_json(silent=True) or {}
    refresh_token_value = str(data.get("refresh_token", "")).strip()

    if not refresh_token_value:
        return jsonify({"success": False, "error": "refresh_token 不能为空"}), 400

    new_creds = refresh_access_token(refresh_token_value)
    if not new_creds:
        return jsonify({
            "success": False,
            "error": "Token 续期失败，请重新登录游戏获取新凭证后再试。",
        }), 502

    expires_at = new_creds.get("expires_at")
    return jsonify({
        "success": True,
        "access_token": new_creds["access_token"],
        "refresh_token": new_creds["refresh_token"],
        "expires_at": expires_at,
        "expires_at_text": _format_expires_at(expires_at),
        "token_valid": check_token_valid(expires_at),
    })