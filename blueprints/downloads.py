from flask import Blueprint, render_template

from utils.json_data import load_json_file

downloads_bp = Blueprint("downloads", __name__)


def load_catalog():
    """读取资料卡片和共享的网盘、群聊入口。"""
    data = load_json_file("downloads.json", default={})
    if not isinstance(data, dict):
        return [], []
    items = data.get("items")
    options = data.get("download_options")
    entries = [
        item for item in items
        if isinstance(item, dict) and item.get("name")
    ] if isinstance(items, list) else []
    links = [
        option for option in options
        if isinstance(option, dict) and option.get("name") and option.get("url")
    ] if isinstance(options, list) else []
    return entries, links


@downloads_bp.route("/downloads")
def index():
    entries, options = load_catalog()
    return render_template(
        "tab_downloads.html",
        entries=entries,
        download_options=options,
    )
