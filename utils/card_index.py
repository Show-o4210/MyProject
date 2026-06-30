"""统一卡牌索引：全项目从 data/index.json 读取。"""

from __future__ import annotations

import re
from typing import Any

from utils.json_data import load_json_file

ZOMBIE_KEYWORDS = [
    "僵尸", "急冻魔", "霹雳舞王", "不死女妖", "无穷小子",
    "海妖", "教授", "锈铁侠", "超尸", "摔跤狂", "Z机甲", "错误",
]


def load_raw_card_index() -> list[dict[str, Any]]:
    data = load_json_file("index.json", default=[])
    return data if isinstance(data, list) else []


def _parse_guid(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_name(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip())


def infer_faction(name_cn: str) -> int:
    """0=植物, 1=僵尸（与旧 uuid.txt 逻辑一致）。"""
    return 1 if any(kw in name_cn for kw in ZOMBIE_KEYWORDS) else 0


def to_deck_editor_cards() -> list[dict[str, Any]]:
    """卡组工坊格式：name / CardGuid / Guid / Faction。"""
    cards: list[dict[str, Any]] = []
    for item in load_raw_card_index():
        guid = _parse_guid(item.get("GUID"))
        if guid is None:
            continue
        name = _clean_name(item.get("NAME_CN"))
        cards.append({
            "name": name,
            "CardGuid": guid,
            "Guid": str(item.get("UUID", "")).strip(),
            "Faction": infer_faction(name),
        })
    return cards


def to_level_editor_cards() -> list[dict[str, Any]]:
    """关卡编辑器格式：guid / name_cn。"""
    cards: list[dict[str, Any]] = []
    for item in load_raw_card_index():
        guid = _parse_guid(item.get("GUID"))
        if guid is None:
            continue
        cards.append({
            "guid": guid,
            "name_cn": _clean_name(item.get("NAME_CN")),
        })
    return cards


def to_phantom_card_index() -> list[dict[str, str]]:
    """幻影工坊格式：GUID / UUID / NAME_CN / TEXTURE_NAME。"""
    index: list[dict[str, str]] = []
    for item in load_raw_card_index():
        guid = _parse_guid(item.get("GUID"))
        if guid is None:
            continue
        index.append({
            "GUID": str(guid),
            "UUID": str(item.get("UUID", "")).strip(),
            "NAME_CN": _clean_name(item.get("NAME_CN")),
            "TEXTURE_NAME": str(item.get("TEXTURE_NAME", "")).strip(),
        })
    return index


def card_index_meta() -> dict[str, Any]:
    index = to_phantom_card_index()
    return {
        "source": "data/index.json",
        "count": len(index),
        "loaded": bool(index),
        "error": "" if index else "未读取到卡牌索引",
    }