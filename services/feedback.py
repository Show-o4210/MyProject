"""意见反馈业务逻辑：校验、组装 payload、写入 Supabase。"""

from __future__ import annotations

import logging
from typing import Any

from database import get_supabase
from security import get_visitor_info

logger = logging.getLogger(__name__)

ALLOWED_TYPES = frozenset({"bug", "feature", "other"})
MAX_CONTENT_LEN = 500
MAX_CONTACT_LEN = 100


class FeedbackValidationError(Exception):
    """请求参数不合法。"""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


class FeedbackStorageError(Exception):
    """持久化失败（配置缺失或 Supabase 异常）。"""

    def __init__(self, message: str = "服务器开小差了，请稍后再试"):
        self.message = message
        super().__init__(message)


def _normalize_payload(data: dict[str, Any] | None) -> dict[str, str]:
    if not data or not isinstance(data, dict):
        raise FeedbackValidationError("请求体不能为空")

    fb_type = str(data.get("type") or "other").strip().lower()
    content = str(data.get("content") or "").strip()
    contact = str(data.get("contact") or "").strip()

    if fb_type not in ALLOWED_TYPES:
        raise FeedbackValidationError("反馈类型无效")

    if not content:
        raise FeedbackValidationError("反馈内容不能为空")
    if len(content) > MAX_CONTENT_LEN:
        raise FeedbackValidationError(f"反馈内容不能超过{MAX_CONTENT_LEN}字")
    if len(contact) > MAX_CONTACT_LEN:
        raise FeedbackValidationError("联系方式过长")

    return {
        "type": fb_type,
        "content": content,
        "contact": contact,
    }


def build_insert_row(normalized: dict[str, str]) -> dict[str, Any]:
    client_ip, user_agent = get_visitor_info()
    return {
        "type": normalized["type"],
        "content": normalized["content"],
        "contact": normalized["contact"],
        "ua_info": {
            "user_agent": user_agent,
            "ip": client_ip,
        },
        "status": "pending",
    }


def create_feedback(data: dict[str, Any] | None) -> dict[str, Any]:
    """
    校验并写入一条反馈。

    Returns:
        写入用的 row（不含数据库生成字段），便于日志/测试。

    Raises:
        FeedbackValidationError: 参数错误
        FeedbackStorageError: 写入失败
    """
    normalized = _normalize_payload(data)
    row = build_insert_row(normalized)

    try:
        get_supabase().table("feedbacks").insert(row).execute()
    except Exception as e:
        # 不把完整用户正文打进日志；只记类型与异常类型
        logger.error(
            "意见反馈写入失败 type=%s err_type=%s err=%s",
            row.get("type"),
            type(e).__name__,
            e,
        )
        raise FeedbackStorageError() from e

    return row
