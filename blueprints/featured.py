"""Public player catalog, read from a deployment snapshot; never proxy images."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from flask import Blueprint, jsonify
from blueprints.version import build_no_cache_response
from utils.json_data import data_file_path

featured_bp = Blueprint("featured", __name__)
ID = re.compile(r"[A-Za-z0-9._-]{1,80}")
SHA = re.compile(r"[a-f0-9]{64}")
HOSTS = {"cdn.jsdelivr.net", "fastly.jsdelivr.net", "gcore.jsdelivr.net"}

def catalog():
    # No external requests, images, database writes or per-user state.
    raw = Path(data_file_path("featured.json")).read_bytes()
    if len(raw) > 131072:
        raise ValueError("Catalog too large")
    data = json.loads(raw)
    if data.get("schema_version") != 2 or not ID.fullmatch(data.get("featured_version", "")):
        raise ValueError("Invalid version")
    works = data.get("works")
    if not isinstance(works, list) or len(works) > 50:
        raise ValueError("Invalid works")
    ids = set()
    for work in works:
        identifier = work.get("id", "")
        if not ID.fullmatch(identifier) or identifier in ids or not SHA.fullmatch(work.get("sha256", "")):
            raise ValueError("Invalid work")
        ids.add(identifier)
        author = work.get("author_id", "")
        if not isinstance(author, str) or not author.strip() or len(author) > 64 or any(ord(c) < 32 or ord(c) == 127 for c in author):
            raise ValueError("Invalid author")
        if not isinstance(work.get("author_words", ""), str) or len(work.get("author_words", "")) > 1000:
            raise ValueError("Invalid author words")
        fallbacks = work.get("image_fallbacks", [])
        if not isinstance(fallbacks, list) or len(fallbacks) > 2:
            raise ValueError("Invalid fallback URLs")
        for url in [work["image_url"]] + fallbacks:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
                raise ValueError("Invalid CDN URL")
            if not re.fullmatch(r"/gh/Show-o4210/DIY-IMG@[a-f0-9]{40}/works/[A-Za-z0-9_./%+-]+", parsed.path) or parsed.query or parsed.fragment:
                raise ValueError("Use immutable reviewed repository URLs")
    return data

def response(version_only=False):
    try:
        data = catalog()
        if version_only:
            data = {"schema_version": data["schema_version"], "featured_version": data["featured_version"]}
        return build_no_cache_response(data)
    except (OSError, ValueError, KeyError, TypeError):
        result = build_no_cache_response({"error": "精选目录暂时不可用"})
        result.status_code = 503
        return result

@featured_bp.get("/api/pvzh-diy/v1/featured/version.json")
def version():
    return response(version_only=True)

@featured_bp.get("/api/pvzh-diy/v1/featured/manifest.json")
def manifest():
    return response()
