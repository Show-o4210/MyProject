from __future__ import annotations

import json
import os
from typing import Any

from utils.card_index import card_index_meta, to_phantom_card_index

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STATIC_CONFIG_PATH = os.path.join(_ROOT, "static", "data", "phantom_config.json")

_cached_config: dict[str, Any] | None = None


def _read_static_config() -> dict[str, Any]:
    if not os.path.exists(_STATIC_CONFIG_PATH):
        return {
            "ok": False,
            "error": "Phantom 静态配置不存在，请确保 static/data/phantom_config.json 已部署。",
        }
    with open(_STATIC_CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data.setdefault("ok", True)
        return data
    return {"ok": False, "error": "Phantom 配置格式无效"}


def _apply_card_index(config: dict[str, Any]) -> dict[str, Any]:
    """卡牌索引统一从 data/index.json 注入（与 /api/phantom/card-index 同源）。"""
    merged = dict(config)
    merged.pop("card_index", None)
    merged.pop("card_index_meta", None)
    merged["card_index"] = to_phantom_card_index()
    merged["card_index_meta"] = card_index_meta()
    return merged


def load_phantom_config() -> dict[str, Any]:
    """加载 Phantom 节点/面板配置；卡牌索引始终来自 data/index.json。"""
    global _cached_config
    if _cached_config is None:
        _cached_config = _read_static_config()
    return _apply_card_index(_cached_config)


def reload_phantom_config() -> dict[str, Any]:
    """清除缓存并重新读取配置（部署更新后可用）。"""
    global _cached_config
    _cached_config = None
    return load_phantom_config()