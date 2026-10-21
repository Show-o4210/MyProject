"""Archived tool URLs; no editor logic or data is loaded by the website."""
from flask import Blueprint, jsonify, render_template

level_editor_bp = Blueprint("level_editor", __name__)


@level_editor_bp.get("/editor")
def index():
    return render_template("editor_archived.html", tool_name="关卡编辑器"), 410


@level_editor_bp.route("/api/editor/init-data", methods=["GET"])
@level_editor_bp.route("/api/editor/ab/list", methods=["GET"])
@level_editor_bp.route("/api/editor/ab/extract", methods=["POST"])
@level_editor_bp.route("/api/editor/ab/pack", methods=["POST"])
def archived_api():
    return jsonify({"status": "error", "archived": True, "message": "关卡编辑器已归档，在线工具已关闭。"}), 410
