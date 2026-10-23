"""Public launcher notifications from one bounded deployment snapshot.

No database, outbound requests, uploaded files, executable content or user state.
The DIY version API and website news remain separate.
"""
import datetime
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from flask import Blueprint

from blueprints.version import build_no_cache_response
from utils.json_data import data_file_path

launcher_bp = Blueprint("launcher", __name__)
MAX_BYTES = 64 * 1024
MAX_ANNOUNCEMENTS = 30
DOWNLOAD_HOSTS = {"pvz-h-tools.onrender.com", "pan.quark.cn"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON property")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("Non-finite JSON number")


def _text(value, limit, *, empty=False, multiline=False):
    if not isinstance(value, str) or len(value) > limit or (not empty and not value.strip()):
        raise ValueError("Invalid text")
    for character in value:
        code = ord(character)
        if code == 0xFFFD or 0xD800 <= code <= 0xDFFF or code == 127:
            raise ValueError("Invalid Unicode text")
        if code < 32 and not (multiline and character in "\n\r\t"):
            raise ValueError("Control character in text")
    return value


def _download_url(value):
    value = _text(value, 4096)
    if "\\" in value or any(character.isspace() for character in value):
        raise ValueError("Invalid download URL")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname not in DOWNLOAD_HOSTS
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443) or parsed.fragment or "#" in value):
        raise ValueError("Untrusted download URL")
    return value


def launcher_manifest():
    with Path(data_file_path("launcher.json")).open("rb") as source:
        raw = source.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Launcher snapshot too large")
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_object, parse_constant=_constant)
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1 or data.get("product") != "pvzh-launcher"
            or data.get("channel") != "stable"):
        raise ValueError("Invalid launcher contract")
    latest = data.get("latest")
    if not isinstance(latest, dict):
        raise ValueError("Missing latest release")
    code = latest.get("release_code")
    if type(code) is not int or not 1 <= code <= 2147483647:
        raise ValueError("Invalid release code")
    clean_latest = {
        "release_code": code,
        "version": _text(latest.get("version"), 80),
        "title": _text(latest.get("title"), 120),
        "notes": _text(latest.get("notes"), 8000, empty=True, multiline=True),
        "download_url": _download_url(latest.get("download_url")),
    }
    announcements = data.get("announcements")
    if not isinstance(announcements, list) or len(announcements) > MAX_ANNOUNCEMENTS:
        raise ValueError("Invalid announcement list")
    clean_announcements = []
    identifiers = set()
    for item in announcements:
        if not isinstance(item, dict):
            raise ValueError("Invalid announcement")
        identifier = item.get("id")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in identifiers:
            raise ValueError("Invalid or duplicate announcement ID")
        identifiers.add(identifier)
        published_at = _text(item.get("published_at"), 10)
        if datetime.date.fromisoformat(published_at).isoformat() != published_at:
            raise ValueError("Invalid date")
        clean_announcements.append({
            "id": identifier,
            "title": _text(item.get("title"), 120),
            "content": _text(item.get("content"), 8000, multiline=True),
            "published_at": published_at,
        })
    return {
        "schema_version": 1,
        "product": "pvzh-launcher",
        "channel": "stable",
        "latest": clean_latest,
        "announcements": clean_announcements,
    }


@launcher_bp.get("/api/pvzh-launcher/v1/manifest.json")
def manifest():
    try:
        # Flask's default ASCII escaping can double a Chinese snapshot's wire
        # size. Keep this route's UTF-8 body within the client's same 64 KiB cap
        # without changing the global JSON provider used by existing clients.
        payload = json.dumps(launcher_manifest(), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_BYTES:
            raise ValueError("Launcher response too large")
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
