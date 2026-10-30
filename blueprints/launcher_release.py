"""Stable launcher releases, isolated from historical R-build notifications.

The release identity is a deployment copy of the client's release.json. Only the
old five-field latest contract is public; ordinary announcements retain one
source in launcher.json. No requests, uploads or configuration writes occur.
"""
import datetime
import json
import math
import re
from pathlib import Path

from flask import Blueprint, request

from blueprints.launcher import (
    IDENTIFIER, MAX_ANNOUNCEMENTS, MAX_BYTES, _constant, _download_url,
    _object, _text,
)
from blueprints.version import build_no_cache_response
from utils.json_data import data_file_path

launcher_release_bp = Blueprint("launcher_release", __name__)
RELEASE_PATH = "/api/pvzh-launcher/v2/manifest.json"
FIELDS = {
    "schema_version", "product", "public_version", "release_code",
    "internal_revision", "channel", "release_date", "title", "notes",
    "download_url",
}
PUBLIC_VERSION = re.compile(r"v[1-9][0-9]*(?:\.(?:0|[1-9][0-9]*)){0,2}")
INTERNAL_REVISION = re.compile(r"R[1-9][0-9]*")


def _finite_number(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite JSON number")
    return number


def _unicode(value):
    # Even discarded fields must not hide unpaired surrogates or replacement
    # characters. Controls are checked by the applicable text field contract.
    if isinstance(value, str):
        if any(ord(c) == 0xFFFD or 0xD800 <= ord(c) <= 0xDFFF for c in value):
            raise ValueError("Invalid Unicode text")
    elif isinstance(value, dict):
        for key, item in value.items():
            _unicode(key)
            _unicode(item)
    elif isinstance(value, list):
        for item in value:
            _unicode(item)


def _read_snapshot(name):
    with Path(data_file_path(name)).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Launcher snapshot too large")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object,
                      parse_constant=_constant, parse_float=_finite_number)
    _unicode(data)
    return data


def validate_launcher_release(data):
    """Validate the ten-field build identity and return only public latest."""
    if (not isinstance(data, dict) or set(data) != FIELDS
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1 or data.get("product") != "pvzh-launcher"
            or data.get("channel") != "stable"):
        raise ValueError("Invalid stable launcher contract")
    code = data["release_code"]
    if type(code) is not int or not 1 <= code <= 2147483647:
        raise ValueError("Invalid release code")
    version = _text(data["public_version"], 80)
    revision = _text(data["internal_revision"], 80)
    if not PUBLIC_VERSION.fullmatch(version) or not INTERNAL_REVISION.fullmatch(revision):
        raise ValueError("Invalid release identity")
    date = _text(data["release_date"], 10)
    if datetime.date.fromisoformat(date).isoformat() != date:
        raise ValueError("Invalid release date")
    return {
        "release_code": code,
        "version": version,
        "title": _text(data["title"], 120),
        "notes": _text(data["notes"], 8000, empty=True, multiline=True),
        "download_url": _download_url(data["download_url"]),
    }


def _announcements(data):
    # Do not validate or use the historical latest field: it belongs only to the
    # old v1 endpoint and must never become a stable release identity.
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1 or data.get("product") != "pvzh-launcher"
            or data.get("channel") != "stable"):
        raise ValueError("Invalid announcement source")
    items = data.get("announcements")
    if not isinstance(items, list) or len(items) > MAX_ANNOUNCEMENTS:
        raise ValueError("Invalid announcement list")
    clean = []
    identifiers = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid announcement")
        identifier = item.get("id")
        if (not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier)
                or identifier in identifiers):
            raise ValueError("Invalid or duplicate announcement ID")
        identifiers.add(identifier)
        date = _text(item.get("published_at"), 10)
        if datetime.date.fromisoformat(date).isoformat() != date:
            raise ValueError("Invalid announcement date")
        clean.append({
            "id": identifier,
            "title": _text(item.get("title"), 120),
            "content": _text(item.get("content"), 8000, multiline=True),
            "published_at": date,
        })
    return clean


def launcher_release_manifest():
    return {
        "schema_version": 1,
        "product": "pvzh-launcher",
        "channel": "stable",
        "latest": validate_launcher_release(_read_snapshot("launcher-release.json")),
        "announcements": _announcements(_read_snapshot("launcher.json")),
    }


def _wire(data):
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_BYTES:
        raise ValueError("Launcher response too large")
    return payload


@launcher_release_bp.after_app_request
def release_headers(response):
    if request.path == RELEASE_PATH:
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@launcher_release_bp.route(RELEASE_PATH, methods=["GET", "HEAD", "OPTIONS"])
def manifest():
    if request.method == "OPTIONS":
        response = build_no_cache_response({})
        response.headers["Allow"] = "GET, HEAD, OPTIONS"
        response.headers["Access-Control-Allow-Methods"] = "GET, HEAD, OPTIONS"
        return response
    try:
        payload = _wire(launcher_release_manifest())
        response = build_no_cache_response({})
        response.set_data(payload)
        return response
    except (OSError, ValueError, KeyError, TypeError, OverflowError, RecursionError):
        response = build_no_cache_response({
            "error": "启动器通知暂时不可用",
            "code": "LAUNCHER_MANIFEST_UNAVAILABLE",
        })
        response.status_code = 503
        return response
