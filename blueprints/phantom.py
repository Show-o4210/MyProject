"""Retired tool URLs retain a clear response; implementation lives in archive/."""
from flask import Blueprint, jsonify, render_template

phantom_bp = Blueprint("phantom", __name__)


@phantom_bp.route("/phantom")
def phantom_page():
    return render_template("phantom_archived.html"), 410


@phantom_bp.route("/api/phantom/ping")
@phantom_bp.route("/api/phantom/config")
def phantom_archived_api():
    return jsonify({"ok": False, "archived": True, "error": "幻影引擎已归档，在线工具已关闭。"}), 410
