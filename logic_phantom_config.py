from __future__ import annotations

import json
from pathlib import Path
from typing import Any

try:
    from flask import current_app
except Exception:  # Flask 不可用时仍可在脚本测试中运行
    current_app = None

MODULE_DIR = Path(__file__).resolve().parent
BASE_DIR = MODULE_DIR
PHANTOM_DATA_DIR = BASE_DIR / "data" / "phantom"
PROJECT_DATA_DIR = BASE_DIR / "data"


def _read_json(filename: str, fallback: Any, base_dir: Path = PHANTOM_DATA_DIR) -> Any:
    path = base_dir / filename
    try:
        # utf-8-sig 兼容 Windows/编辑器保存时可能带上的 BOM。
        with path.open("r", encoding="utf-8-sig") as f:
            return json.load(f)
    except FileNotFoundError:
        return fallback
    except json.JSONDecodeError as exc:
        raise ValueError(f"Phantom 配置文件格式错误: {path}: {exc}") from exc


def _as_text(value: Any) -> str:
    return str(value if value is not None else "").strip()


def _normalize_card_index_item(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None

    # 兼容大小写/不同命名，真正匹配仍然只用 GUID。
    guid = _as_text(item.get("GUID") or item.get("guid") or item.get("Guid") or item.get("id") or item.get("ID"))
    if not guid:
        return None

    return {
        "GUID": guid,
        "UUID": _as_text(item.get("UUID") or item.get("uuid") or item.get("PrefabName") or item.get("prefabName")),
        "NAME_CN": _as_text(item.get("NAME_CN") or item.get("name_cn") or item.get("NameCN") or item.get("name") or item.get("NAME")),
        "TEXTURE_NAME": _as_text(item.get("TEXTURE_NAME") or item.get("texture_name") or item.get("TextureName")),
    }


def _extract_index_list(raw: Any) -> list[Any]:
    """兼容 index.json 外层为数组或对象两种写法。

    推荐格式：
      [{"GUID":"1", "UUID":"...", "NAME_CN":"..."}]

    也兼容：
      {"cards": [...]}
      {"index": [...]}
      {"items": [...]}
    """
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("cards", "index", "items", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
    return []


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        try:
            key = str(path.resolve())
        except Exception:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def _project_roots() -> list[Path]:
    """返回可能的项目根目录。

    有些项目会把 logic_phantom_config.py 放在根目录；也有人会把它移动到
    blueprints/ 或其他包内。只用 __file__.parent 时，一旦文件位置变化，
    就会去错误的目录找 data/index.json。这里改成多路径扫描。
    """
    roots: list[Path] = []

    # Flask 真实项目根目录，最可信。
    try:
        if current_app is not None:
            roots.append(Path(current_app.root_path))
    except Exception:
        pass

    # 当前运行目录。Render / gunicorn / python app.py 情况下通常就是项目根。
    roots.append(Path.cwd())

    # 模块所在目录及其父目录，兼容文件被放到 blueprints/ 等子目录。
    roots.append(MODULE_DIR)
    roots.extend(MODULE_DIR.parents)

    return _unique_paths(roots)


def _format_path(path: Path, root: Path | None = None) -> str:
    try:
        if root is not None and path.resolve().is_relative_to(root.resolve()):
            return str(path.resolve().relative_to(root.resolve()))
    except Exception:
        pass
    return str(path)


def load_card_index() -> tuple[list[dict[str, str]], dict[str, Any]]:
    """读取 card index，并返回详细诊断信息。

    优先读取项目根目录的 data/index.json；也兼容 data/phantom/index.json。
    如果读不到，会把实际扫描过的路径返回给前端。
    """
    roots = _project_roots()
    candidates: list[Path] = []
    for root in roots:
        candidates.extend([
            root / "data" / "index.json",
            root / "data" / "phantom" / "index.json",
        ])
    candidates = _unique_paths(candidates)

    primary_root = roots[0] if roots else BASE_DIR
    checked = [
        {
            "path": _format_path(path, primary_root),
            "exists": path.exists(),
            "is_file": path.is_file(),
        }
        for path in candidates
    ]

    meta: dict[str, Any] = {
        "source": "",
        "count": 0,
        "loaded": False,
        "error": "",
        "checked": checked,
        "roots": [_format_path(root) for root in roots[:6]],
    }

    for path in candidates:
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            items = []
            for item in _extract_index_list(raw):
                normalized = _normalize_card_index_item(item)
                if normalized:
                    items.append(normalized)
            meta.update({
                "source": _format_path(path, primary_root),
                "count": len(items),
                "loaded": True,
                "error": "" if items else "索引文件已读取，但没有找到有效 GUID 条目。请检查字段名是否为 GUID/UUID/NAME_CN。",
            })
            return items, meta
        except Exception as exc:  # noqa: BLE001
            meta.update({
                "source": _format_path(path, primary_root),
                "count": 0,
                "loaded": False,
                "error": f"读取索引失败：{exc}",
            })
            return [], meta

    meta["error"] = "未找到 data/index.json。请看 checked 列表确认后端实际扫描路径。"
    return [], meta


def load_phantom_config() -> dict[str, Any]:
    """读取 Phantom Web 端配置资源。"""
    base = _read_json("phantom_config.json", {})
    fonts = _read_json("fonts.json", {"fonts": []})
    skill_library = _read_json("skill_library.json", {"categories": [], "total_nodes": 0})
    localization = {
        "zh-CN": _read_json("localization_zh.json", {}),
        "en-US": _read_json("localization_en.json", {}),
    }
    card_index, card_index_meta = load_card_index()

    return {
        "ok": True,
        "version": base.get("version", "unknown"),
        "stage": base.get("stage", "resource-layer"),
        "default_language": base.get("default_language", "zh-CN"),
        "supported_languages": base.get("supported_languages", ["zh-CN"]),
        "default_font": base.get("default_font", "system-ui"),
        "enums": base.get("enums", {}),
        "fonts": fonts.get("fonts", []),
        "localization": localization,
        "skill_library": skill_library,
        "card_index": card_index,
        "card_index_meta": card_index_meta,
        "notes": base.get("notes", []),
    }
