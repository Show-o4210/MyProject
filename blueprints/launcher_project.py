"""Bounded plain-text project message and acknowledgements for the launcher.

This is an independent read-only deployment snapshot. It does not edit the
notification/version API, contact GitHub, accept submissions or expose URLs.
"""
import datetime
import json
from pathlib import Path

from flask import Blueprint, request

from blueprints.version import build_no_cache_response
from utils.json_data import data_file_path

launcher_project_bp = Blueprint("launcher_project", __name__)
MAX_BYTES = 64 * 1024
PROJECT_PATH = "/api/pvzh-launcher/v1/project.json"
FIELDS = {
    "schema_version", "product", "updated_at", "title", "paragraphs",
    "repository_note", "supporters", "contributors",
}


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON property")
        value[key] = item
    return value


def _constant(_value):
    raise ValueError("Non-finite JSON number")


def _text(value, limit, *, empty=False, multiline=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError("Invalid project text")
    for character in value:
        code = ord(character)
        if code == 0xFFFD or 0xD800 <= code <= 0xDFFF or code == 127:
            raise ValueError("Invalid Unicode text")
        if code < 32 and not (multiline and character in "\n\r\t"):
            raise ValueError("Control character in text")
    return value


def _texts(value, count, limit, *, empty=False, multiline=False):
    if not isinstance(value, list) or len(value) > count:
        raise ValueError("Invalid project text list")
    return [_text(item, limit, empty=empty, multiline=multiline) for item in value]


def _wire(data):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("Project response too large")
    return payload


def validate_launcher_project(data):
    """Validate the exact public contract without mutating the caller's data."""
    if (not isinstance(data, dict) or set(data) != FIELDS
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1 or data.get("product") != "pvzh-launcher"):
        raise ValueError("Invalid launcher project contract")
    updated_at = _text(data["updated_at"], 10)
    if datetime.date.fromisoformat(updated_at).isoformat() != updated_at:
        raise ValueError("Invalid project date")
    clean = {
        "schema_version": 1,
        "product": "pvzh-launcher",
        "updated_at": updated_at,
        "title": _text(data["title"], 120),
        "paragraphs": _texts(data["paragraphs"], 20, 2000, empty=True, multiline=True),
        "repository_note": _text(data["repository_note"], 400, empty=True),
        "supporters": _texts(data["supporters"], 100, 80),
        "contributors": _texts(data["contributors"], 100, 80),
    }
    _wire(clean)
    return clean


def launcher_project_snapshot():
    with Path(data_file_path("launcher-project.json")).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Project snapshot too large")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    return validate_launcher_project(data)


@launcher_project_bp.after_app_request
def project_headers(response):
    # Routing rejects write methods before a blueprint is selected. Apply this
    # endpoint's headers to those 405s and request-budget errors as well.
    if request.path == PROJECT_PATH:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@launcher_project_bp.route(PROJECT_PATH, methods=["GET", "HEAD", "OPTIONS"])
def project():
    if request.method == "OPTIONS":
        response = build_no_cache_response({})
        response.headers["Allow"] = "GET, HEAD, OPTIONS"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        return response
    try:
        payload = _wire(launcher_project_snapshot())
        response = build_no_cache_response({})
        response.set_data(payload)
        return response
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        response = build_no_cache_response({
            "error": "项目留言暂时不可用",
            "code": "LAUNCHER_PROJECT_UNAVAILABLE",
        })
        response.status_code = 503
        return response
