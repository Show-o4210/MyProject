from flask import Blueprint, jsonify, make_response
from utils.json_data import load_json_file

version_bp = Blueprint("version", __name__)

DEFAULT_VERSION_DATA = {
    "version": "v4.4.5",
    "version_code": 40405,
    "update_title": "版本更新 v4.4.5",
    "update_log": "热拉上了",
    "download_url": "https://github.com/Show-o4210/PVZH-DIY/releases/download/%E6%AD%A3%E5%BC%8F%E7%89%88/app-release.apk",
    "force_update": False,
    "release_date": "2026-07-21"
}


def get_version_info():
    data = load_json_file("version.json", default=DEFAULT_VERSION_DATA)
    if not isinstance(data, dict):
        return DEFAULT_VERSION_DATA
    return data


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

