from __future__ import annotations

from flask import Blueprint, jsonify, render_template

from .logic_phantom_config import load_phantom_config

phantom_bp = Blueprint("phantom", __name__)


@phantom_bp.route("/phantom")
def phantom_page():
    """Phantom 卡牌 JSON 创作工坊。"""
    return render_template("phantom.html")


@phantom_bp.route("/api/phantom/ping")
def phantom_ping():
    return jsonify({"ok": True, "module": "phantom", "stage": "json-creator-v1"})


@phantom_bp.route("/api/phantom/config")
def phantom_config():
    return jsonify(load_phantom_config())