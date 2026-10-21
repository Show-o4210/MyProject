"""Bound the Unity unpack request stream before multipart parsing."""
from flask import jsonify, request
from werkzeug.exceptions import RequestEntityTooLarge

JSON_BODY_LIMITS = {"unity.unpack": 141 * 1024 * 1024}


def apply_json_body_limit():
    limit = JSON_BODY_LIMITS.get(request.endpoint)
    if limit is not None:
        current = request.max_content_length
        request.max_content_length = min(current, limit) if current is not None else limit


def init_small_json_limits(app):
    app.before_request(apply_json_body_limit)

    @app.errorhandler(RequestEntityTooLarge)
    def body_too_large(error):
        if request.endpoint in JSON_BODY_LIMITS:
            return jsonify({"status": "error", "message": "请求内容过大，请缩小文件后重试"}), 413
        return error
