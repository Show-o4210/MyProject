from flask import Blueprint, render_template, request

from blueprints.card_sender import CARD_IDS


ea_tools_bp = Blueprint("ea_tools", __name__)


@ea_tools_bp.route("/ea-tools")
def ea_tools_page():
    operation = request.args.get("operation", "cards").strip().lower()
    if operation not in {"cards", "packs"}:
        operation = "cards"
    return render_template(
        "ea_tools.html",
        current_tab="ea_tools",
        initial_operation=operation,
        card_ids_count=len(CARD_IDS),
    )
