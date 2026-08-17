from flask import Blueprint, redirect, render_template, url_for

from extensions import limiter
from utils.json_data import load_json_file

downloads_bp = Blueprint("downloads", __name__)

DEFAULT_DOWNLOAD_OPTIONS = [
    {
        "id": "quark",
        "name": "夸克网盘",
        "description": "打开 PVZH 相关内容合集，适合直接查找和保存文件。",
        "url": "https://pan.quark.cn/s/92d058b77b5f",
        "icon": "cloud_download",
        "action": "打开网盘",
    },
    {
        "id": "qq-group",
        "name": "QQ 群",
        "description": "加入群聊【【PVZH】Main】，获取资源、通知与使用帮助。",
        "url": "https://qm.qq.com/q/PayU4f00iQ",
        "icon": "group_add",
        "action": "加入群聊",
    },
]


def _normalize_item(raw):
    if not isinstance(raw, dict) or not raw.get("id"):
        return None

    item = dict(raw)
    images = item.get("images") if isinstance(item.get("images"), list) else []
    cover = str(item.get("cover") or "").strip()
    if not cover and images and isinstance(images[0], str):
        cover = images[0].strip()

    item["images"] = images
    item["cover"] = cover
    item["usage"] = item.get("usage") if isinstance(item.get("usage"), list) else []
    item["notes"] = item.get("notes") if isinstance(item.get("notes"), list) else []
    return item


def load_catalog():
    """读取下载目录，返回统一条目列表和全站共享下载方式。"""
    data = load_json_file("downloads.json", default={})
    if not isinstance(data, dict):
        return [], DEFAULT_DOWNLOAD_OPTIONS

    entries = []
    for section in data.get("sections") or []:
        if not isinstance(section, dict):
            continue
        for raw in section.get("items") or []:
            item = _normalize_item(raw)
            if item:
                entries.append(item)

    options = []
    for option in data.get("download_options") or []:
        if not isinstance(option, dict) or not option.get("id") or not option.get("url"):
            continue
        options.append({
            "id": str(option["id"]),
            "name": str(option.get("name") or option["id"]),
            "description": str(option.get("description") or ""),
            "url": str(option["url"]).strip(),
            "icon": str(option.get("icon") or "open_in_new"),
            "action": str(option.get("action") or "打开"),
        })

    return entries, options or DEFAULT_DOWNLOAD_OPTIONS


def find_item(item_id):
    entries, _options = load_catalog()
    return next((item for item in entries if item.get("id") == item_id), None)


@downloads_bp.route("/downloads")
def index():
    entries, options = load_catalog()
    return render_template(
        "tab_downloads.html",
        entries=entries,
        download_options=options,
    )


@downloads_bp.route("/downloads/<item_id>")
def detail(item_id):
    item = find_item(item_id)
    if not item:
        return render_template("error.html", msg="未找到该资源，可能已被下架。"), 404

    _entries, options = load_catalog()
    return render_template(
        "download_detail.html",
        tool=item,
        download_options=options,
    )


def _primary_download_url():
    _entries, options = load_catalog()
    return options[0]["url"] if options else url_for("downloads.index")


# 兼容已经分享出去的旧下载地址。下载内容现已统一到共享入口。
@downloads_bp.route("/api/download/<item_id>")
@limiter.limit("20 per minute")
def trigger_download(item_id):
    if not find_item(item_id):
        return render_template("error.html", msg="未找到该资源，可能已被下架。"), 404
    return redirect(_primary_download_url())


@downloads_bp.route("/api/download/<item_id>/<file_id>")
@limiter.limit("20 per minute")
def trigger_file_download(item_id, file_id):
    if not find_item(item_id):
        return render_template("error.html", msg="未找到该资源，可能已被下架。"), 404
    return redirect(_primary_download_url())
