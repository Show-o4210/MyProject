# database.py
"""Supabase 客户端单例管理器，稳定管理普通端与管理员特权端。"""

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from supabase import Client


class SupabaseManager:
    _client_instance: Optional["Client"] = None
    _admin_client_instance: Optional["Client"] = None

    @classmethod
    def get_client(cls) -> "Client":
        """获取标准的普通客户端（使用 ANON KEY）"""
        if cls._client_instance is None:
            from supabase import create_client
            from config import Config

            if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
                raise RuntimeError("Supabase 未配置：请检查 SUPABASE_URL 和 SUPABASE_KEY")
            
            cls._client_instance = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)
        return cls._client_instance

    @classmethod
    def get_admin_client(cls) -> "Client":
        """获取管理员特权客户端（严格绑定 SERVICE_KEY）"""
        if cls._admin_client_instance is None:
            from supabase import create_client
            from config import Config

            if not Config.SUPABASE_URL or not Config.SUPABASE_SERVICE_KEY:
                raise RuntimeError("Supabase 管理端未配置：请检查 SUPABASE_URL 和 SUPABASE_SERVICE_KEY")
            
            # 显式构造，并强制关闭 options 的外部干扰，确保 service_role 绝对生效
            cls._admin_client_instance = create_client(
                supabase_url=Config.SUPABASE_URL,
                supabase_key=Config.SUPABASE_SERVICE_KEY
            )
        return cls._admin_client_instance


def get_supabase() -> "Client":
    """对外的保持原有兼容的 API 接口"""
    return SupabaseManager.get_client()


def get_supabase_admin() -> "Client":
    """对外的保持原有兼容的 API 接口"""
    return SupabaseManager.get_admin_client()