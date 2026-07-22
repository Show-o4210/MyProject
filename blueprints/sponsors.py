from flask import Blueprint, jsonify, make_response, request
from utils.json_data import load_json_file

sponsors_bp = Blueprint("sponsors", __name__)

DEFAULT_SPONSORS_DATA = {
    "sponsors": [
        "赞赏者名单示例1",
        "赞赏者名单示例2"
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


@sponsors_bp.route("/api/sponsors", methods=["GET"])
@sponsors_bp.route("/sponsors", methods=["GET"])
@sponsors_bp.route("/api/thanks", methods=["GET"])
@sponsors_bp.route("/thanks", methods=["GET"])
def get_sponsors():
    info = get_sponsors_info()
    fmt = request.args.get("format", "").strip().lower()
    if fmt in ("text", "txt"):
        sponsors_list = info.get("sponsors", []) if isinstance(info, dict) else info
        if isinstance(sponsors_list, list):
            text_output = "\n".join(str(s) for s in sponsors_list)
        else:
            text_output = str(sponsors_list)
        return build_no_cache_response(text_output, is_json=False)
    return build_no_cache_response(info, is_json=True)


@sponsors_bp.route("/sponsors.txt", methods=["GET"])
@sponsors_bp.route("/thanks.txt", methods=["GET"])
def get_sponsors_txt():
    info = get_sponsors_info()
    sponsors_list = info.get("sponsors", []) if isinstance(info, dict) else info
    if isinstance(sponsors_list, list):
        text_output = "\n".join(str(s) for s in sponsors_list)
    else:
        text_output = str(sponsors_list)
    return build_no_cache_response(text_output, is_json=False)
