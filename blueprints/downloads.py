from flask import Blueprint, render_template
from utils.json_data import load_json_file

downloads_bp = Blueprint("downloads", __name__)


@downloads_bp.get("/downloads")
def index():
    data = load_json_file("downloads.json", default={})
    return render_template("tab_downloads.html", download_url=data["url"])
