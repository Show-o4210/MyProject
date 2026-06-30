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
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"读取 {filename} 失败: {e}")
        return default