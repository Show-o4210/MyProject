"""统一卡牌索引：全项目从 data/index_new.json 读取。"""

from __future__ import annotations

import re
from typing import Any

from utils.json_data import load_json_file

INDEX_FILENAME = "index_new.json"

# 旧数据无 FACTION 字段时的兜底关键词（优先使用 index 内 FACTION）
_ZOMBIE_KEYWORDS = (
    "僵尸", "急冻魔", "霹雳舞王", "不死女妖", "无穷小子",
    "海妖", "教授", "锈铁侠", "超尸", "摔跤狂", "Z机甲", "错误",
)

_ZOMBIE_FACTION_TOKENS = frozenset({
    "1", "僵尸", "zombie", "zombies",
})
_PLANT_FACTION_TOKENS = frozenset({
    "0", "植物", "plant", "plants",
})


def load_raw_card_index() -> list[dict[str, Any]]:
    data = load_json_file(INDEX_FILENAME, default=[])
    return data if isinstance(data, list) else []


def _parse_guid(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _clean_name(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "").strip())


def _infer_faction_from_name(name_cn: str) -> int:
    """名称关键词兜底：0=植物, 1=僵尸。"""
    return 1 if any(kw in name_cn for kw in _ZOMBIE_KEYWORDS) else 0


def parse_faction(value: Any, name_cn: str = "") -> int:
    """将 FACTION 字段规范为 0=植物 / 1=僵尸。

    优先使用 index_new.json 的 FACTION（如「植物」「僵尸」），
    也兼容数字与英文枚举；缺省时再按中文名关键词推断。
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return _infer_faction_from_name(name_cn)

    if isinstance(value, bool):
        return int(value)

    if isinstance(value, (int, float)):
        return 1 if int(value) == 1 else 0

    text = str(value).strip()
    lowered = text.lower()
    if lowered in _ZOMBIE_FACTION_TOKENS or text == "僵尸":
        return 1
    if lowered in _PLANT_FACTION_TOKENS or text == "植物":
        return 0

    try:
        return 1 if int(text) == 1 else 0
    except (TypeError, ValueError):
        return _infer_faction_from_name(name_cn or text)


def faction_to_phantom(faction: int) -> str:
    """卡组/关卡用 0/1 → 幻影工坊 Plants/Zombies。"""
    return "Zombies" if faction == 1 else "Plants"


def to_deck_editor_cards() -> list[dict[str, Any]]:
    """卡组工坊格式：name / CardGuid / Guid / Faction(0|1)。"""
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
            "Faction": parse_faction(item.get("FACTION"), name),
        })
    return cards


def to_level_editor_cards() -> list[dict[str, Any]]:
    """关卡编辑器格式：guid / name_cn / faction。"""
    cards: list[dict[str, Any]] = []
    for item in load_raw_card_index():
        guid = _parse_guid(item.get("GUID"))
        if guid is None:
            continue
        name = _clean_name(item.get("NAME_CN"))
        cards.append({
            "guid": guid,
            "name_cn": name,
            "faction": parse_faction(item.get("FACTION"), name),
        })
    return cards


def to_phantom_card_index() -> list[dict[str, str]]:
    """幻影工坊格式：GUID / UUID / NAME_CN / TEXTURE_NAME / FACTION / TYPE / NAME_EN。"""
    index: list[dict[str, str]] = []
    for item in load_raw_card_index():
        guid = _parse_guid(item.get("GUID"))
        if guid is None:
            continue
        name = _clean_name(item.get("NAME_CN"))
        faction_n = parse_faction(item.get("FACTION"), name)
        index.append({
            "GUID": str(guid),
            "UUID": str(item.get("UUID", "")).strip(),
            "NAME_CN": name,
            "TEXTURE_NAME": str(item.get("TEXTURE_NAME", "")).strip(),
            "FACTION": "僵尸" if faction_n == 1 else "植物",
            "TYPE": str(item.get("TYPE", "")).strip(),
            "NAME_EN": str(item.get("NAME_EN", "")).strip(),
            # 幻影 UI 枚举值
            "FACTION_ENUM": faction_to_phantom(faction_n),
        })
    return index


def card_index_meta() -> dict[str, Any]:
    index = to_phantom_card_index()
    return {
        "source": f"data/{INDEX_FILENAME}",
        "count": len(index),
        "loaded": bool(index),
        "error": "" if index else "未读取到卡牌索引",
    }
