import json
import os
from typing import Any


def project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_file_path(filename: str) -> str:
    return os.path.join(project_root(), "data", filename)


def load_json_file(filename: str, default: Any = None) -> Any:
    """从 data/ 目录读取 JSON 文件，失败时返回 default。"""
    path = data_file_path(filename)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "rb") as f:
            raw = f.read(128 * 1024 + 1)
        if len(raw) > 128 * 1024:
            raise ValueError("Snapshot exceeds size limit")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
    except (OSError, ValueError, RecursionError):
        return default


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate property")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError("Non-finite JSON number")
