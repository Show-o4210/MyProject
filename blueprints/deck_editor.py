"""Archived tool URLs; no editor logic or data is loaded by the website."""
from flask import Blueprint, jsonify, render_template

deck_editor_bp = Blueprint("deck_editor", __name__)


@deck_editor_bp.get("/deck-editor")
def index():
    return render_template("editor_archived.html", tool_name="卡组编辑器"), 410


@deck_editor_bp.route("/api/init_data", methods=["GET"])
@deck_editor_bp.route("/api/quick_export", methods=["POST"])
def archived_api():
    return jsonify({"status": "error", "archived": True, "message": "卡组编辑器已归档，在线工具已关闭。"}), 410
