#!/usr/bin/env python3
"""校验 data/downloads.json 结构与约定。

用法（在项目根目录）:
  python scripts/validate_downloads.py

退出码: 0 通过；1 有错误。
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_PATH = os.path.join(ROOT, "data", "downloads.json")

def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    if not os.path.exists(DATA_PATH):
        print(f"[ERROR] 找不到 {DATA_PATH}")
        return 1

    with open(DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        print("[ERROR] 根节点必须是 object")
        return 1

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        print("[ERROR] 缺少 sections[]")
        return 1

    download_options = data.get("download_options")
    if not isinstance(download_options, list) or not download_options:
        errors.append("缺少 download_options[]")
    else:
        option_ids: set[str] = set()
        for oi, option in enumerate(download_options):
            prefix = f"download_options[{oi}]"
            if not isinstance(option, dict):
                errors.append(f"{prefix} 不是 object")
                continue
            option_id = option.get("id")
            if not option_id:
                errors.append(f"{prefix} 缺少 id")
            elif option_id in option_ids:
                errors.append(f"重复的 download option id: {option_id}")
            else:
                option_ids.add(option_id)
            if not option.get("name"):
                errors.append(f"{prefix} 缺少 name")
            if not (option.get("url") or "").strip():
                errors.append(f"{prefix} 缺少 url")

    seen_item_ids: set[str] = set()
    seen_section_ids: set[str] = set()

    for si, section in enumerate(sections):
        if not isinstance(section, dict):
            errors.append(f"sections[{si}] 不是 object")
            continue
        sid = section.get("id")
        if not sid:
            errors.append(f"sections[{si}] 缺少 id")
            continue
        if sid in seen_section_ids:
            errors.append(f"重复的 section id: {sid}")
        seen_section_ids.add(sid)

        items = section.get("items")
        if items is None:
            errors.append(f"section `{sid}` 缺少 items")
            continue
        if not isinstance(items, list):
            errors.append(f"section `{sid}`.items 必须是 array")
            continue

        for ii, item in enumerate(items):
            prefix = f"section `{sid}` items[{ii}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} 不是 object")
                continue
            iid = item.get("id")
            if not iid:
                errors.append(f"{prefix} 缺少 id")
                continue
            if iid in seen_item_ids:
                errors.append(f"重复的 item id: {iid}")
            seen_item_ids.add(iid)

            if not item.get("name"):
                errors.append(f"{prefix} (`{iid}`) 缺少 name")

            if item.get("url") or item.get("files"):
                warnings.append(f"`{iid}` 仍含独立下载链接；当前界面只使用 download_options[]")

            for field in ("series_id", "series_name"):
                val = item.get(field)
                if val is not None and not isinstance(val, str):
                    errors.append(f"`{iid}`.{field} 必须是 string")

            if item.get("series_order") is not None:
                try:
                    int(item["series_order"])
                except (TypeError, ValueError):
                    errors.append(f"`{iid}`.series_order 必须是整数")

            images = item.get("images")
            if images is not None and not isinstance(images, list):
                errors.append(f"`{iid}`.images 必须是 array")

    # 系列完整性提示
    series_map: dict[str, list[str]] = {}
    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            sid = (item.get("series_id") or "").strip()
            if sid:
                series_map.setdefault(sid, []).append(item.get("id") or "?")
    for sid, members in series_map.items():
        if len(members) < 2:
            warnings.append(f"系列 `{sid}` 仅 1 个成员，互链暂不可见: {members}")

    print(f"校验文件: {DATA_PATH}")
    print(f"分区数: {len(sections)}  条目数: {len(seen_item_ids)}")
    print(f"统一下载方式: {len(download_options) if isinstance(download_options, list) else 0}")
    print()

    for w in warnings:
        print(f"[WARN] {w}")
    for e in errors:
        print(f"[ERROR] {e}")

    if errors:
        print(f"\n失败: {len(errors)} 个错误, {len(warnings)} 个警告")
        return 1

    print(f"\n通过: 0 错误, {len(warnings)} 个警告")
    return 0


if __name__ == "__main__":
    sys.exit(main())
