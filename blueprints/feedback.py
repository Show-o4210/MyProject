import logging

from flask import Blueprint, request, jsonify, render_template

from extensions import limiter
from security import visitor_ip_key
from services.feedback import (
    create_feedback,
    FeedbackValidationError,
    FeedbackStorageError,
)

feedback_bp = Blueprint("feedback", __name__)
logger = logging.getLogger(__name__)


@feedback_bp.route("/feedback")
def feedback_page():
    return render_template("feedback.html")


@feedback_bp.route("/api/feedback/submit", methods=["POST"])
@limiter.limit("3 per hour", key_func=visitor_ip_key)
def submit_feedback():
    data = request.get_json(silent=True)

    try:
        create_feedback(data)
        return jsonify({"ok": True, "message": "提交成功"}), 200
    except FeedbackValidationError as e:
        return jsonify({"ok": False, "error": e.message, "code": "VALIDATION_ERROR"}), 400
    except FeedbackStorageError as e:
        # 配置/表/权限问题对运维可见 code；文案可直接展示给用户
        http_status = 503 if e.code in {"TABLE_NOT_FOUND", "CONFIG_ERROR", "PERMISSION_DENIED"} else 500
        return jsonify({"ok": False, "error": e.message, "code": e.code}), http_status
    except Exception as e:
        logger.error("意见反馈未预期异常: %s: %s", type(e).__name__, e)
        return jsonify(
            {"ok": False, "error": "服务器开小差了，请稍后再试", "code": "INTERNAL_ERROR"}
        ), 500
