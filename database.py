# database.py
"""Supabase 客户端懒加载，避免启动时强依赖 pydantic/supabase 链。"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from supabase import Client

_client: Optional["Client"] = None
_init_error: Optional[str] = None


def get_supabase() -> "Client":
    """获取 Supabase 客户端，首次调用时才初始化。"""
    global _client, _init_error

    if _client is not None:
        return _client

    if _init_error is not None:
        raise RuntimeError(_init_error)

    try:
        from supabase import create_client
        from config import Config

        if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
            _init_error = "Supabase 未配置：请在 .env 中设置 SUPABASE_URL 和 SUPABASE_KEY"
            raise RuntimeError(_init_error)

        _client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        return _client
    except Exception as e:
        _init_error = f"Supabase 初始化失败: {e}"
        raise RuntimeError(_init_error) from e