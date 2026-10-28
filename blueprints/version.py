from datetime import date
from urllib.parse import urlsplit

from flask import Blueprint, jsonify, make_response
from utils.json_data import load_json_file

version_bp = Blueprint("version", __name__)

def get_version_info():
    data = load_json_file("version.json")
    if not isinstance(data, dict):
        raise ValueError("Version snapshot must be an object")
    for field, limit in (("version", 80), ("update_title", 120), ("update_log", 16000)):
        value = data.get(field)
        if not isinstance(value, str) or len(value) > limit or (field != "update_log" and not value.strip()):
            raise ValueError("Invalid version text")
    code = data.get("version_code")
    if type(code) is not int or not 1 <= code <= 2147483647:
        raise ValueError("Invalid version code")
    if type(data.get("force_update")) is not bool:
        raise ValueError("Invalid update flag")
    released = data.get("release_date")
    if not isinstance(released, str) or date.fromisoformat(released).isoformat() != released:
        raise ValueError("Invalid release date")
    url = data.get("download_url")
    if not isinstance(url, str) or len(url) > 4096 or "\\" in url or any(c.isspace() for c in url):
        raise ValueError("Invalid download URL")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port not in (None, 443)):
        raise ValueError("Invalid download URL")
    minimum = data.get("minimum_supported_version")
    if minimum is not None and (not isinstance(minimum, str) or not minimum.strip() or len(minimum) > 80):
        raise ValueError("Invalid minimum version")
    minimum_code = data.get("minimum_supported_version_code")
    if minimum_code is not None and (type(minimum_code) is not int or not 1 <= minimum_code <= code):
        raise ValueError("Invalid minimum version code")
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
    try:
        return build_no_cache_response(get_version_info())
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        response = build_no_cache_response({"error": "版本信息暂时不可用", "code": "VERSION_UNAVAILABLE"})
        response.status_code = 503
        return response


