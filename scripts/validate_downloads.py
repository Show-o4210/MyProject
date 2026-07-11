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

# Supabase / 静态托管建议路径（文档约定，非强制）
STORAGE_HINT = "workshop-downloads/{section_or_mods|tools}/{item_id}/{file_id}.ext"


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
        # 兼容旧根 tools
        if isinstance(data.get("tools"), list):
            warnings.append("使用旧根键 tools[]，建议迁移为 sections[]")
            sections = [
                {"id": "tools", "name": "tools", "items": data["tools"]},
            ]
        else:
            print("[ERROR] 缺少 sections[]")
            return 1

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

            files = item.get("files")
            has_files = isinstance(files, list) and len(files) > 0
            kind = (item.get("kind") or "").strip().lower()
            url = (item.get("url") or "").strip()

            if has_files or kind == "bundle":
                if not has_files:
                    errors.append(f"bundle `{iid}` 必须至少有 1 个 file")
                else:
                    seen_file_ids: set[str] = set()
                    rec_count = 0
                    for fi, f in enumerate(files):
                        fp = f"{prefix} files[{fi}]"
                        if not isinstance(f, dict):
                            errors.append(f"{fp} 不是 object")
                            continue
                        fid = f.get("id")
                        if not fid:
                            errors.append(f"{fp} 缺少 id")
                            continue
                        if fid in seen_file_ids:
                            errors.append(f"bundle `{iid}` 内重复 file id: {fid}")
                        seen_file_ids.add(fid)
                        if not (f.get("url") or "").strip():
                            errors.append(f"file `{iid}/{fid}` 缺少 url")
                        if not f.get("name"):
                            warnings.append(f"file `{iid}/{fid}` 缺少 name")
                        if f.get("recommended"):
                            rec_count += 1
                        notes = f.get("notes")
                        if notes is not None and not isinstance(notes, list):
                            errors.append(f"file `{iid}/{fid}`.notes 必须是 array")
                    if rec_count == 0 and not url:
                        warnings.append(
                            f"bundle `{iid}` 无 recommended 子文件且无 item.url，"
                            "将无法提供「下载推荐项」默认入口"
                        )
                    if rec_count > 1:
                        warnings.append(f"bundle `{iid}` 有多个 recommended，仅第一个生效")
            else:
                if not url:
                    errors.append(f"single `{iid}` 缺少 url")

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
    print(f"存储命名建议: {STORAGE_HINT}")
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
