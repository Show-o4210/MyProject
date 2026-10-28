"""Tombstones for old website/tool URLs; never inspect or parse request bodies."""
from flask import Blueprint, jsonify, render_template

retired_bp = Blueprint("retired", __name__)

WEB_PATHS = ("/unity", "/editor", "/deck-editor", "/phantom", "/downloads", "/tools")
TOOL_PATHS = (
    "/unpack", "/repack", "/unity/inspect", "/unity/validate-repack",
    "/api/init_data", "/api/quick_export",
    "/api/editor/init-data", "/api/editor/ab/list",
    "/api/editor/ab/extract", "/api/editor/ab/pack",
    "/api/phantom/ping", "/api/phantom/config",
)


def retired_page():
    return render_template("retired.html"), 410


def retired_tool():
    return jsonify({
        "ok": False, "success": False, "status": "error", "archived": True,
        "code": "WEB_TOOLS_RETIRED",
        "error": "Web 工具服务已停止，工具能力正在逐步迁往 PVZH Mod 启动器。",
        "message": "请访问首页查看站点调整说明。", "notice_url": "/",
    }), 410


for path in WEB_PATHS:
    retired_bp.add_url_rule(path, endpoint=path, view_func=retired_page)
for path in TOOL_PATHS:
    retired_bp.add_url_rule(path, endpoint=path, view_func=retired_tool,
                            methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
