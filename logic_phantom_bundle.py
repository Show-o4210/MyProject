"""Phantom Web AssetBundle 注入工具。

该模块是从原 PySide 工具的 bundle_packer.py 迁移出来的 Web 后端版本：
- 不依赖桌面端 app_logging / path_utils；
- 接收 v0.3 前端生成的 card_data 字典；
- 在 Unity Bundle 中寻找 cards 资源并覆盖对应 GUID；
- 输出重新打包后的 AssetBundle。
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, Tuple

logger = logging.getLogger(__name__)


def clean_json_string(value: Any) -> Any:
    """清理 Unity TextAsset 中常见的不可见字符与中文标点。"""
    if not isinstance(value, str):
        return value
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", value)
    cleaned = cleaned.replace("\ufeff", "").strip()
    cleaned = cleaned.replace("，", ",").replace("“", '"').replace("”", '"')
    return cleaned


def _decode_json_payload(payload: Any) -> Tuple[Dict[str, Any], str]:
    """把 TextAsset / typetree 中的 JSON 载荷解成 dict，并返回原始类型标记。"""
    if isinstance(payload, bytes):
        text = clean_json_string(payload.decode("utf-8-sig"))
        return json.loads(text), "bytes"
    if isinstance(payload, str):
        text = clean_json_string(payload)
        return json.loads(text), "str"
    if isinstance(payload, dict):
        return payload, "dict"
    raise ValueError(f"不支持的数据载荷类型：{type(payload).__name__}")


def _encode_json_payload(data: Dict[str, Any], payload_type: str) -> Any:
    """按原载荷类型写回 JSON。"""
    if payload_type == "dict":
        return data
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    if payload_type == "bytes":
        return text.encode("utf-8")
    return text


def _merge_card_data(target_dict: Dict[str, Any], modded_card_dict: Dict[str, Any]) -> int:
    """按 GUID 覆盖写入卡牌数据，返回写入数量。"""
    count = 0
    for guid, card_data in (modded_card_dict or {}).items():
        if not guid:
            continue
        target_dict[str(guid)] = card_data
        count += 1
    return count


def update_bundle_with_card_data(
    bundle_in_path: str | os.PathLike[str],
    bundle_out_path: str | os.PathLike[str],
    modded_card_dict: Dict[str, Any],
    target_asset_name: str = "cards",
) -> Tuple[bool, str, Dict[str, Any]]:
    """向 Unity AssetBundle 注入卡牌 JSON。

    Args:
        bundle_in_path: 原始 AssetBundle 路径。
        bundle_out_path: 输出 AssetBundle 路径。
        modded_card_dict: 形如 {"GUID": card_entry} 的 card_data 字典。
        target_asset_name: 目标 TextAsset / MonoBehaviour 名称关键字，默认 cards。

    Returns:
        (ok, message, detail)
    """
    bundle_in_path = Path(bundle_in_path)
    bundle_out_path = Path(bundle_out_path)
    detail: Dict[str, Any] = {"target_asset_name": target_asset_name, "updated_cards": 0, "asset_name": ""}

    if not bundle_in_path.exists():
        return False, f"找不到原始 Bundle 文件：{bundle_in_path}", detail
    if not isinstance(modded_card_dict, dict) or not modded_card_dict:
        return False, "没有可注入的卡牌数据。请先确认当前工程中至少有一张带 GUID 的卡牌。", detail

    try:
        import UnityPy  # type: ignore
    except ImportError:
        return False, "缺少依赖 UnityPy：请先在 requirements.txt 中加入 UnityPy 并安装。", detail

    try:
        env = UnityPy.load(str(bundle_in_path))
        modified = False

        for obj in env.objects:
            if obj.type.name not in ["TextAsset", "MonoBehaviour"]:
                continue

            # 优先 TypeTree：对 TextAsset / MonoBehaviour 兼容性最好。
            if getattr(obj, "serialized_type", None) and obj.serialized_type.nodes:
                try:
                    tree = obj.read_typetree()
                    asset_name = str(tree.get("m_Name", ""))
                    if target_asset_name not in asset_name:
                        continue

                    data_key = None
                    target_payload = None
                    for key in ("m_Script", "m_Text", "script"):
                        if key in tree:
                            data_key = key
                            target_payload = tree[key]
                            break

                    if data_key is None:
                        # 某些 MonoBehaviour typetree 可能已经是根级 dict。
                        data_key = "ROOT"
                        target_payload = tree

                    target_dict, payload_type = _decode_json_payload(target_payload)
                    updated = _merge_card_data(target_dict, modded_card_dict)

                    if data_key == "ROOT":
                        tree.clear()
                        tree.update(target_dict)
                    else:
                        tree[data_key] = _encode_json_payload(target_dict, payload_type)

                    obj.save_typetree(tree)
                    modified = True
                    detail.update({"updated_cards": updated, "asset_name": asset_name, "mode": "typetree"})
                    break
                except Exception as exc:  # pragma: no cover - 依赖具体 bundle 结构
                    logger.exception("Phantom Bundle TypeTree 注入失败，继续尝试下一个对象：%s", exc)
                    continue

            # 备用：老 bundle / 无 typetree 情况。
            try:
                data = obj.read()
                asset_name = str(getattr(data, "name", getattr(data, "m_Name", "")))
                if target_asset_name not in asset_name:
                    continue

                raw_text = getattr(data, "script", getattr(data, "text", getattr(data, "m_Script", b"")))
                target_dict, payload_type = _decode_json_payload(raw_text)
                updated = _merge_card_data(target_dict, modded_card_dict)
                new_payload = _encode_json_payload(target_dict, payload_type)

                if hasattr(data, "script"):
                    data.script = new_payload
                elif hasattr(data, "text"):
                    data.text = new_payload
                elif hasattr(data, "m_Script"):
                    data.m_Script = new_payload
                else:
                    continue

                data.save()
                modified = True
                detail.update({"updated_cards": updated, "asset_name": asset_name, "mode": "object"})
                break
            except Exception as exc:  # pragma: no cover
                logger.exception("Phantom Bundle 备用注入失败，继续尝试下一个对象：%s", exc)
                continue

        if not modified:
            return False, f"在 Bundle 中未找到名称包含 '{target_asset_name}' 的 JSON 数据节点。", detail

        bundle_out_path.parent.mkdir(parents=True, exist_ok=True)
        with bundle_out_path.open("wb") as fp:
            fp.write(env.file.save(packer="lz4"))

        return True, "AssetBundle 注入并打包成功。", detail
    except Exception as exc:  # pragma: no cover
        logger.exception("Phantom Bundle 打包发生严重异常：%s", exc)
        return False, f"打包发生严重异常：{exc}", detail


def _summarize_card_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """返回 card_data 的轻量摘要，避免把完整大 JSON 直接塞进预检响应。"""
    keys = [str(k) for k in (data or {}).keys()]
    return {
        "card_count": len(keys),
        "sample_guids": keys[:12],
    }


def _read_card_payload_from_object(obj: Any, target_asset_name: str) -> Tuple[bool, Dict[str, Any], Dict[str, Any]]:
    """尝试从 UnityPy 对象中读取目标 cards JSON。"""
    if obj.type.name not in ["TextAsset", "MonoBehaviour"]:
        return False, {}, {}

    # 优先 TypeTree。
    if getattr(obj, "serialized_type", None) and obj.serialized_type.nodes:
        try:
            tree = obj.read_typetree()
            asset_name = str(tree.get("m_Name", ""))
            if target_asset_name not in asset_name:
                return False, {}, {}

            data_key = None
            target_payload = None
            for key in ("m_Script", "m_Text", "script"):
                if key in tree:
                    data_key = key
                    target_payload = tree[key]
                    break
            if data_key is None:
                data_key = "ROOT"
                target_payload = tree

            target_dict, payload_type = _decode_json_payload(target_payload)
            info = {
                "name": asset_name,
                "type": obj.type.name,
                "path_id": getattr(obj, "path_id", None),
                "mode": "typetree",
                "data_key": data_key,
                "payload_type": payload_type,
                **_summarize_card_data(target_dict),
            }
            return True, target_dict, info
        except Exception as exc:  # pragma: no cover
            return False, {}, {"error": str(exc), "type": obj.type.name, "mode": "typetree"}

    # 备用读取。
    try:
        data = obj.read()
        asset_name = str(getattr(data, "name", getattr(data, "m_Name", "")))
        if target_asset_name not in asset_name:
            return False, {}, {}
        raw_text = getattr(data, "script", getattr(data, "text", getattr(data, "m_Script", b"")))
        target_dict, payload_type = _decode_json_payload(raw_text)
        info = {
            "name": asset_name,
            "type": obj.type.name,
            "path_id": getattr(obj, "path_id", None),
            "mode": "object",
            "payload_type": payload_type,
            **_summarize_card_data(target_dict),
        }
        return True, target_dict, info
    except Exception as exc:  # pragma: no cover
        return False, {}, {"error": str(exc), "type": obj.type.name, "mode": "object"}


def inspect_bundle_cards(
    bundle_in_path: str | os.PathLike[str],
    target_asset_name: str = "cards",
    include_data: bool = False,
) -> Tuple[bool, str, Dict[str, Any]]:
    """预检 AssetBundle：查找并解析 cards JSON 资源。"""
    bundle_in_path = Path(bundle_in_path)
    detail: Dict[str, Any] = {
        "target_asset_name": target_asset_name,
        "matched": False,
        "resources": [],
    }
    if not bundle_in_path.exists():
        return False, f"找不到 Bundle 文件：{bundle_in_path}", detail

    try:
        import UnityPy  # type: ignore
    except ImportError:
        return False, "缺少依赖 UnityPy：请先在 requirements.txt 中加入 UnityPy 并安装。", detail

    try:
        env = UnityPy.load(str(bundle_in_path))
        parse_errors = []
        for obj in env.objects:
            if obj.type.name not in ["TextAsset", "MonoBehaviour"]:
                continue
            found, card_data, info = _read_card_payload_from_object(obj, target_asset_name)
            if info.get("error"):
                parse_errors.append(info)
            if not found:
                continue
            detail["matched"] = True
            detail["resources"].append(info)
            if include_data:
                detail["card_data"] = card_data
            # 目前只需要第一处匹配的 cards 资源。
            break

        if parse_errors and not detail["matched"]:
            detail["parse_errors"] = parse_errors[:8]
        if not detail["matched"]:
            return False, f"未找到名称包含 '{target_asset_name}' 且可解析为 JSON 的 cards 资源。", detail
        return True, "AssetBundle 预检通过。", detail
    except Exception as exc:  # pragma: no cover
        logger.exception("Phantom Bundle 预检发生严重异常：%s", exc)
        return False, f"预检发生严重异常：{exc}", detail


def _simple_value(entry: Dict[str, Any], path: str) -> Any:
    current: Any = entry
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _diff_values(before: Any, after: Any) -> bool:
    return json.dumps(before, ensure_ascii=False, sort_keys=True) != json.dumps(after, ensure_ascii=False, sort_keys=True)


def diff_card_data(original_data: Dict[str, Any], modded_data: Dict[str, Any]) -> Dict[str, Any]:
    """对比原始 card_data 与当前 Phantom 工程输出。"""
    original_data = original_data or {}
    modded_data = modded_data or {}
    changed_cards = []
    added_cards = []
    removed_cards = []
    fields = [
        ("prefabName", "Prefab"),
        ("baseId", "BaseId"),
        ("color", "Color"),
        ("set", "Set"),
        ("rarity", "Rarity"),
        ("setAndRarityKey", "Set/Rarity Key"),
        ("craftingBuy", "制作价格"),
        ("craftingSell", "分解价格"),
        ("displaySunCost", "费用"),
        ("displayAttack", "攻击"),
        ("displayHealth", "生命"),
        ("faction", "阵营"),
        ("ignoreDeckLimit", "IgnoreDeckLimit"),
        ("isPower", "Power"),
        ("isPrimaryPower", "PrimaryPower"),
        ("isFighter", "Fighter"),
        ("isEnv", "Environment"),
        ("isAquatic", "Aquatic"),
        ("isTeamup", "Teamup"),
        ("subtypes", "显示种族"),
        ("tags", "显示标签"),
        ("special_abilities", "根目录特殊能力"),
        ("subtype_affinities", "AI 种族倾向"),
        ("subtype_affinity_weights", "AI 种族权重"),
        ("tag_affinities", "AI 标签倾向"),
        ("tag_affinity_weights", "AI 标签权重"),
        ("card_affinities", "AI 卡牌倾向"),
        ("card_affinity_weights", "AI 卡牌权重"),
        ("entity.components", "组件列表"),
    ]

    original_keys = set(map(str, original_data.keys()))
    modded_keys = set(map(str, modded_data.keys()))

    for guid in sorted(modded_keys - original_keys, key=lambda x: (len(x), x)):
        added_cards.append({"guid": guid, "after": modded_data.get(guid)})
    for guid in sorted(original_keys - modded_keys, key=lambda x: (len(x), x)):
        removed_cards.append({"guid": guid, "before": original_data.get(guid)})

    for guid in sorted(original_keys & modded_keys, key=lambda x: (len(x), x)):
        before = original_data.get(guid) or {}
        after = modded_data.get(guid) or {}
        changes = []
        for path, label in fields:
            before_value = _simple_value(before, path)
            after_value = _simple_value(after, path)
            if _diff_values(before_value, after_value):
                changes.append({"field": path, "label": label, "before": before_value, "after": after_value})
        if changes:
            changed_cards.append({"guid": guid, "changes": changes})

    return {
        "summary": {
            "original_count": len(original_keys),
            "modded_count": len(modded_keys),
            "added": len(added_cards),
            "removed": len(removed_cards),
            "changed": len(changed_cards),
        },
        "added_cards": added_cards,
        "removed_cards": removed_cards,
        "changed_cards": changed_cards,
    }
