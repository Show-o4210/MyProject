from flask import Blueprint, jsonify, make_response
from utils.json_data import load_json_file

sponsors_bp = Blueprint("sponsors", __name__)

DEFAULT_SPONSORS_DATA = {
    "sponsors": [
        "夫不赖 #2026-7-19",
        "夫不赖 #2026-7-21",
        "咲梢汇星辰༅࿐ #2026-7-19",
        "滕佳宏小雀瓜 #2026-7-19",
        "鱼 #2026-7-21",
        "小云 #2026-7-21",
        "小云 #2026-7-22",
        "西门吹雪  #2026-7-21",
        "志志 #2026-7-21",
        "Grrreenpig #2026-7-21",
        "北海 #2026-7-21",
        "是朵朵啊 #2026-7-21",
        "愤怒的wan豆 #2026-7-22",
        "以及默默使用本工具的你"
    ],
    "updated": "2026-07-22"
}


def get_sponsors_info():
    data = load_json_file("sponsors.json", default=DEFAULT_SPONSORS_DATA)
    if isinstance(data, list):
        return {
            "sponsors": data,
            "updated": "2026-07-22"
        }
    if not isinstance(data, dict):
        return DEFAULT_SPONSORS_DATA
    return data


def build_no_cache_response(data):
    resp = make_response(jsonify(data))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp


@sponsors_bp.route("/api/sponsors", methods=["GET"])
@sponsors_bp.route("/sponsors", methods=["GET"])
@sponsors_bp.route("/api/thanks", methods=["GET"])
@sponsors_bp.route("/thanks", methods=["GET"])
@sponsors_bp.route("/sponsors.txt", methods=["GET"])
@sponsors_bp.route("/thanks.txt", methods=["GET"])
def get_sponsors():
    info = get_sponsors_info()
    return build_no_cache_response(info)

