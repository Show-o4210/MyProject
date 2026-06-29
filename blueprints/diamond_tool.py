import json
import re
import time
from typing import Any, Tuple

import requests
from flask import Blueprint, jsonify, render_template, request

from extensions import limiter
from logic_ea_api import (
    DEFAULT_CLIENT_VERSION,
    DEFAULT_CONTENT_VERSION,
    DEFAULT_PLATFORM,
    DEFAULT_REQUEST_TIMEOUT,
    build_pvzh_headers,
    post_daily_login,
    post_league_sync,
    resolve_request_credentials,
)

diamond_tool_bp = Blueprint("diamond_tool", __name__)

SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,64}$")
SAFE_CONTENT_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,128}$")
SAFE_PLATFORM_RE = re.compile(r"^[0-9A-Za-z._ -]{1,32}$")
DEFAULT_GEMS = 10000
MAX_REPEAT = 5


def clean_field(value: Any, default: str, pattern: re.Pattern) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    if not pattern.match(text):
        return default
    return text


def parse_upstream_body(response: requests.Response) -> Tuple[Any, str]:
    response_text = response.text or ""
    try:
        return response.json(), response_text
    except Exception:
        try:
            return json.loads(response_text), response_text
        except Exception:
            return response_text, response_text


@diamond_tool_bp.route("/diamond-tool")
def diamond_tool_page():
    return render_template("diamond_tool.html", current_tab="diamond_tool")


@diamond_tool_bp.route("/api/generate-diamonds", methods=["POST"])
@limiter.limit("10 per minute")
def generate_diamonds():
    """钻石生成：每日登录 + 联赛奖励同步。"""
    data = request.get_json(silent=True) or {}

    token, persona_id, auth_meta = resolve_request_credentials(data)
    raw_repeat = data.get("repeat", 1)
    raw_gems = data.get("gems", DEFAULT_GEMS)

    client_version = clean_field(
        data.get("client_version"), DEFAULT_CLIENT_VERSION, SAFE_VERSION_RE
    )
    content_version = clean_field(
        data.get("content_version"), DEFAULT_CONTENT_VERSION, SAFE_CONTENT_VERSION_RE
    )
    platform = clean_field(data.get("platform"), DEFAULT_PLATFORM, SAFE_PLATFORM_RE)

    if not token:
        return jsonify({"success": False, "error": "EADP-AUTH-TOKEN 不能为空"}), 400
    if not persona_id:
        return jsonify({"success": False, "error": "EADP-PERSONA-ID 不能为空"}), 400

    try:
        repeat = int(raw_repeat)
        if repeat <= 0 or repeat > MAX_REPEAT:
            return jsonify({
                "success": False,
                "error": f"生成轮次必须在 1 ~ {MAX_REPEAT} 之间",
            }), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "生成轮次必须是有效数字"}), 400

    try:
        gems = int(raw_gems)
        if gems <= 0 or gems > 10000:
            return jsonify({"success": False, "error": "钻石数量必须在 1 ~ 10000 之间"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "钻石数量必须是有效数字"}), 400

    headers = build_pvzh_headers(
        token,
        persona_id,
        client_version=client_version,
        content_version=content_version,
        platform=platform,
    )

    rounds = []
    success_count = 0

    try:
        for round_index in range(1, repeat + 1):
            round_result = {
                "round": round_index,
                "daily_login": None,
                "league_sync": None,
                "success": False,
            }

            login_resp = post_daily_login(persona_id, headers, timeout=DEFAULT_REQUEST_TIMEOUT)
            login_body, login_text = parse_upstream_body(login_resp)
            login_ok = login_resp.status_code == 200
            round_result["daily_login"] = {
                "success": login_ok,
                "status_code": login_resp.status_code,
                "response": login_body,
            }

            if round_index < repeat:
                time.sleep(0.5)

            sync_resp = post_league_sync(
                persona_id,
                headers,
                gems=gems,
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
            sync_body, sync_text = parse_upstream_body(sync_resp)
            sync_ok = sync_resp.status_code == 200
            round_result["league_sync"] = {
                "success": sync_ok,
                "status_code": sync_resp.status_code,
                "response": sync_body,
            }

            round_result["success"] = login_ok and sync_ok
            if round_result["success"]:
                success_count += 1

            rounds.append(round_result)

            if round_index < repeat:
                time.sleep(0.5)

        all_success = success_count == repeat
        error_message = None
        if not all_success:
            error_message = f"钻石生成部分失败：{success_count}/{repeat} 轮成功，请查看各轮详情。"

        return jsonify({
            "success": all_success,
            "error": error_message,
            "success_count": success_count,
            "total_rounds": repeat,
            "gems_per_round": gems,
            "rounds": rounds,
            "auth_meta": auth_meta,
            "request_meta": {
                "platform": platform,
                "client_version": client_version,
                "content_version": content_version,
                "gems": gems,
            },
        })

    except requests.Timeout:
        return jsonify({"success": False, "error": "请求超时，请稍后重试"}), 504
    except requests.ConnectionError:
        return jsonify({"success": False, "error": "网络连接失败，服务器无法连接 PVZH 接口"}), 503
    except Exception as e:
        return jsonify({"success": False, "error": f"请求失败: {str(e)}"}), 500