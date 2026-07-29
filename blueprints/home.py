from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from xml.sax.saxutils import escape as xml_escape

from flask import Blueprint, Response, render_template, request

from utils.json_data import load_json_file, project_root

home_bp = Blueprint('home', __name__)

SPECIAL_CLOSING = "以及默默使用本工具的你"
AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# 公网规范域名（GSC / robots Sitemap 指向）
SITE_BASE = os.environ.get("SITE_BASE_URL", "https://pvz-h-tools.onrender.com").rstrip("/")

# 固定收录页（不含 /api/、/security/ 等）
_STATIC_SITEMAP_PAGES = [
    {"path": "/", "changefreq": "daily", "priority": "1.0"},
    {"path": "/downloads", "changefreq": "weekly", "priority": "0.9"},
    {"path": "/unity", "changefreq": "weekly", "priority": "0.9"},
    {"path": "/deck-editor", "changefreq": "weekly", "priority": "0.8"},
    {"path": "/editor", "changefreq": "weekly", "priority": "0.8"},
    {"path": "/phantom", "changefreq": "weekly", "priority": "0.8"},
    {"path": "/card-sender", "changefreq": "monthly", "priority": "0.7"},
    {"path": "/pack-buyer", "changefreq": "monthly", "priority": "0.7"},
    {"path": "/feedback", "changefreq": "monthly", "priority": "0.5"},
    {"path": "/tools", "changefreq": "monthly", "priority": "0.5"},
]


def _site_base_url() -> str:
    """优先 SITE_BASE_URL；本地调试时可用当前 Host。"""
    env = os.environ.get("SITE_BASE_URL", "").strip().rstrip("/")
    if env:
        return env
    try:
        if request and request.host_url:
            return request.host_url.rstrip("/")
    except RuntimeError:
        pass
    return SITE_BASE


def load_news_data():
    data = load_json_file('news.json', default={})
    return {
        'announcements': data.get('announcements', []),
        'changelogs': data.get('changelogs', []),
    }


def _list_avatar_files() -> dict[str, str]:
    """name (without ext) -> filename under static/images/thanks/"""
    avatar_dir = os.path.join(project_root(), "static", "images", "thanks")
    mapping: dict[str, str] = {}
    if not os.path.isdir(avatar_dir):
        return mapping
    for filename in os.listdir(avatar_dir):
        stem, ext = os.path.splitext(filename)
        if ext.lower() in AVATAR_EXTS and stem:
            mapping[stem] = filename
    return mapping


def load_thanks_page_data() -> dict[str, Any]:
    """
    Build page-only thanks data from sponsors.json.
    Does not touch /thanks or /api/thanks APK endpoints.
    """
    data = load_json_file("sponsors.json", default={})
    if isinstance(data, list):
        raw_list = data
        updated = ""
    elif isinstance(data, dict):
        raw_list = data.get("sponsors", []) or []
        updated = str(data.get("updated") or "")
    else:
        raw_list = []
        updated = ""

    avatars = _list_avatar_files()
    people: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    closing: str | None = None

    for entry in raw_list:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if not text:
            continue
        if text == SPECIAL_CLOSING or text.startswith(SPECIAL_CLOSING):
            closing = SPECIAL_CLOSING
            continue

        if "#" in text:
            name_part, date_part = text.rsplit("#", 1)
            name = name_part.strip()
            date = date_part.strip()
        else:
            name = text
            date = ""

        if not name:
            continue

        if name not in people:
            people[name] = {
                "name": name,
                "dates": [],
                "avatar": avatars.get(name),
                "initial": name[0],
            }
            order.append(name)

        if date and date not in people[name]["dates"]:
            people[name]["dates"].append(date)

    return {
        "people": [people[n] for n in order],
        "closing": closing,
        "updated": updated,
        "total": len(order),
    }


@home_bp.route('/')
def index():
    news_data = load_news_data()
    return render_template(
        'index.html',
        current_tab='home',
        announcements=news_data['announcements'],
        changelogs=news_data['changelogs'],
    )


@home_bp.route('/tools')
def tools():
    thanks = load_thanks_page_data()
    return render_template(
        'tab_thanks.html',
        current_tab='thanks',
        people=thanks["people"],
        closing=thanks["closing"],
        updated=thanks["updated"],
        total=thanks["total"],
    )


def _build_robots_txt() -> str:
    """根路径 /robots.txt 内容。优先读 static/robots.txt，保证与构建脚本一致。"""
    static_path = os.path.join(project_root(), "static", "robots.txt")
    if os.path.isfile(static_path):
        try:
            with open(static_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                # 若静态文件 Sitemap 域名过旧，仍以运行时 base 覆盖最后一行 Sitemap
                if "Sitemap:" not in content:
                    content += f"\n\nSitemap: {_site_base_url()}/sitemap.xml"
                return content + "\n"
        except OSError:
            pass

    base = _site_base_url()
    return (
        "User-agent: *\n"
        "Allow: /\n"
        "\n"
        "Disallow: /api/\n"
        "Disallow: /security/\n"
        "\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )


def _iter_sitemap_urls() -> list[dict[str, str]]:
    """组装 sitemap URL 列表：固定页 + downloads.json 详情。"""
    today = datetime.now(timezone.utc).date().isoformat()
    base = _site_base_url()
    urls: list[dict[str, str]] = []

    for page in _STATIC_SITEMAP_PAGES:
        urls.append({
            "loc": f"{base}{page['path']}",
            "lastmod": today,
            "changefreq": page["changefreq"],
            "priority": page["priority"],
        })

    catalog = load_json_file("downloads.json", default={})
    sections = catalog.get("sections", []) if isinstance(catalog, dict) else []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if not item_id:
                continue
            urls.append({
                "loc": f"{base}/downloads/{item_id}",
                "lastmod": today,
                "changefreq": "weekly",
                "priority": "0.6",
            })

    return urls


def _build_sitemap_xml() -> str:
    """动态生成 sitemap.xml（爬虫要的是根路径 /sitemap.xml，不是 /static/）。"""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in _iter_sitemap_urls():
        lines.append(
            "  <url>"
            f"<loc>{xml_escape(url['loc'])}</loc>"
            f"<lastmod>{xml_escape(url['lastmod'])}</lastmod>"
            f"<changefreq>{xml_escape(url['changefreq'])}</changefreq>"
            f"<priority>{xml_escape(url['priority'])}</priority>"
            "</url>"
        )
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


@home_bp.route("/robots.txt")
def robots_txt():
    """
    爬虫默认请求 /robots.txt。
    WhiteNoise 只挂了 prefix=/static/，static/robots.txt 不会出现在根路径，
    必须显式路由，否则日志里会是 bot → 404。
    """
    body = _build_robots_txt()
    resp = Response(body, mimetype="text/plain")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@home_bp.route("/sitemap.xml")
def sitemap_xml():
    """根路径 sitemap，供 Googlebot / Bingbot 抓取。"""
    body = _build_sitemap_xml()
    resp = Response(body, mimetype="application/xml")
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp
