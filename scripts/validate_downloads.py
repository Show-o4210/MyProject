#!/usr/bin/env python3
"""校验资料卡片及共享下载入口：python scripts/validate_downloads.py。"""

import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "downloads.json"


def check_records(records, label, required, allowed):
    errors = []
    if not isinstance(records, list):
        return [f"{label} 必须是数组"]
    seen = set()
    for index, record in enumerate(records):
        prefix = f"{label}[{index}]"
        if not isinstance(record, dict):
            errors.append(f"{prefix} 必须是对象")
            continue
        for field in required:
            value = record.get(field)
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{prefix}.{field} 必须是非空字符串")
        for field, value in record.items():
            if field not in allowed:
                errors.append(f"{prefix} 不支持字段 {field}")
            elif not isinstance(value, str):
                errors.append(f"{prefix}.{field} 必须是字符串")
        record_id = record.get("id")
        if isinstance(record_id, str):
            if record_id in seen:
                errors.append(f"{prefix} 的 id 重复：{record_id}")
            seen.add(record_id)
    return errors


def main():
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"[ERROR] 无法读取下载配置：{error}")
        return 1
    if not isinstance(data, dict):
        print("[ERROR] 根节点必须是对象")
        return 1
    errors = [f"根节点不支持字段 {key}" for key in data if key not in {"items", "download_options"}]
    errors += check_records(data.get("items"), "items", {"id", "name"}, {"id", "name", "tag", "icon"})
    options = data.get("download_options")
    errors += check_records(options, "download_options", {"id", "name", "url"}, {"id", "name", "url", "icon"})
    if isinstance(options, list):
        if not options:
            errors.append("至少需要一个下载入口")
        for index, option in enumerate(options):
            if isinstance(option, dict) and isinstance(option.get("url"), str):
                try:
                    url = urlsplit(option["url"])
                    valid = url.scheme in {"https", "http"} and bool(url.netloc)
                except ValueError:
                    valid = False
                if not valid:
                    errors.append(f"download_options[{index}].url 必须是 HTTP(S) 链接")
    for error in errors:
        print(f"[ERROR] {error}")
    if errors:
        return 1
    print(f"通过：{len(data['items'])} 项资料，{len(options)} 个共享入口")
    return 0


if __name__ == "__main__":
    sys.exit(main())
