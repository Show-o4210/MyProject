# config.py
import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


def _parse_email_set(raw: str) -> set[str]:
    return {email.strip().lower() for email in (raw or "").split(",") if email.strip()}


class Config:
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-insecure-change-me")
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)

    # 邀请码门禁开关，本地调试可设 GATE_ENABLED=false
    GATE_ENABLED = os.environ.get("GATE_ENABLED", "true").lower() in {"1", "true", "yes", "on"}

    # 管理员 Supabase Auth 邮箱白名单（逗号分隔，2 人）
    ADMIN_EMAILS = _parse_email_set(os.environ.get("ADMIN_EMAILS", ""))

    MAX_CONTENT_LENGTH = 20 * 1024 * 1024