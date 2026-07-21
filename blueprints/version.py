from flask import Blueprint, jsonify, make_response, request
from utils.json_data import load_json_file

version_bp = Blueprint("version", __name__)

DEFAULT_VERSION_DATA = {
    "version": "v4.4.3",
    "version_code": 40403,
    "update_title": "版本更新 v4.4.3",
    "update_log": "1. 优化连接与版本检查响应速度；\n2. 预留版本更新接口与直链支持。",
    "download_url": "",
    "force_update": False,
    "release_date": "2026-07-21"
}


def get_version_info():
    data = load_json_file("version.json", default=DEFAULT_VERSION_DATA)
    if not isinstance(data, dict):
        return DEFAULT_VERSION_DATA
    return data


def build_no_cache_response(data_or_text, is_json=True):
    if is_json:
        resp = make_response(jsonify(data_or_text))
    else:
        resp = make_response(str(data_or_text), 200)
        resp.headers["Content-Type"] = "text/plain; charset=utf-8"

    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@version_bp.route("/api/version", methods=["GET"])
@version_bp.route("/version", methods=["GET"])
def get_version():
    info = get_version_info()
    fmt = request.args.get("format", "").strip().lower()
    if fmt in ("text", "txt"):
        return build_no_cache_response(info.get("version", "v4.4.3"), is_json=False)
    return build_no_cache_response(info, is_json=True)


@version_bp.route("/version.txt", methods=["GET"])
def get_version_txt():
    info = get_version_info()
    return build_no_cache_response(info.get("version", "v4.4.3"), is_json=False)
