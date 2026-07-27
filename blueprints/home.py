from __future__ import annotations

import os
from typing import Any

from flask import Blueprint, render_template

from utils.json_data import load_json_file, project_root

home_bp = Blueprint('home', __name__)

SPECIAL_CLOSING = "以及默默使用本工具的你"
AVATAR_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


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
