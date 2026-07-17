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

    def __init__(self, message: str = "服务器开小差了，请稍后再试", *, code: str = "STORAGE_ERROR"):
        self.message = message
        self.code = code
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
            "user_agent": (user_agent or "")[:2000],
            "ip": client_ip or "unknown",
        },
        "status": "pending",
    }


def _classify_storage_error(err: BaseException) -> FeedbackStorageError:
    """把 Supabase/PostgREST 异常归类成可运维的错误码（不把用户正文回传前端）。"""
    msg = str(err)
    low = msg.lower()

    # PostgREST 表不存在 / schema cache 未刷新时常表现为 HTTP 404 + PGRST205
    if (
        "pgrst205" in low
        or "could not find the table" in low
        or "does not exist" in low
        or "404" in low and "feedbacks" in low
    ):
        return FeedbackStorageError(
            "反馈表未就绪或未暴露给 API，请在 Supabase 执行 sql/feedbacks.sql 并刷新 schema cache",
            code="TABLE_NOT_FOUND",
        )

    # anon 仅有 INSERT、无 SELECT 时，默认 returning=representation 会失败
    if (
        "permission denied" in low
        or "42501" in low
        or "row-level security" in low
        or "rls" in low
    ):
        return FeedbackStorageError(
            "写入权限被拒：请确认 anon 有 INSERT，且后端使用 returning=minimal",
            code="PERMISSION_DENIED",
        )

    if "jwt" in low or "invalid api key" in low or "401" in low:
        return FeedbackStorageError(
            "Supabase 密钥无效：请检查 Render 上的 SUPABASE_URL / SUPABASE_KEY（anon key）",
            code="CONFIG_ERROR",
        )

    if "supabase 未配置" in low or "初始化失败" in low:
        return FeedbackStorageError(
            "Supabase 未配置：请在环境变量中设置 SUPABASE_URL 与 SUPABASE_KEY",
            code="CONFIG_ERROR",
        )

    return FeedbackStorageError()


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
        # 关键：feedbacks 对 anon 仅 GRANT INSERT，无 SELECT。
        # supabase-py 默认 returning=representation 会要求读回插入行，
        # PostgREST 在无 SELECT 权限时失败（常见日志/表象为 404 或 permission denied）。
        from postgrest.types import ReturnMethod

        get_supabase().table("feedbacks").insert(
            row, returning=ReturnMethod.minimal
        ).execute()
    except FeedbackValidationError:
        raise
    except Exception as e:
        # 不把完整用户正文打进日志；只记类型与异常类型
        logger.error(
            "意见反馈写入失败 type=%s err_type=%s err=%s",
            row.get("type"),
            type(e).__name__,
            e,
        )
        raise _classify_storage_error(e) from e

    return row
