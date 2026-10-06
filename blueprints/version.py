from flask import Blueprint, jsonify, make_response
from utils.json_data import load_json_file

version_bp = Blueprint("version", __name__)

DEFAULT_VERSION_DATA = {
    "version": "v4.13.1",
    "version_code": 41301,
    "update_title": "文字输入修复补丁 v4.13.1",
    "update_log": "修复文字输入时的键盘遮挡与光标行可见性。",
    "download_url": "https://pan.quark.cn/s/92d058b77b5f",
    "force_update": True,
    "release_date": "2026-10-03",
    "minimum_supported_version": None,
    "minimum_supported_version_code": None
}


def get_version_info():
    data = load_json_file("version.json", default=DEFAULT_VERSION_DATA)
    if not isinstance(data, dict):
        return DEFAULT_VERSION_DATA
    return {**data, "minimum_supported_version": data.get("minimum_supported_version"),
            "minimum_supported_version_code": data.get("minimum_supported_version_code")}


def build_no_cache_response(data):
    resp = make_response(jsonify(data))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@version_bp.route("/api/version", methods=["GET"])
@version_bp.route("/version", methods=["GET"])
@version_bp.route("/version.txt", methods=["GET"])
def get_version():
    info = get_version_info()
    return build_no_cache_response(info)

