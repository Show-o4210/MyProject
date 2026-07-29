from flask import Blueprint, render_template, request, send_file, jsonify, after_this_request
import UnityPy
import json
import json5
import zipfile
import tempfile
import re
from utils.json_clean import clean_json_string
import io
import csv
import os
import shutil
import threading
import gc
from PIL import Image

unity_bp = Blueprint('unity', __name__)

from extensions import acquire_unity_lock, release_unity_lock

MAX_BUNDLE_SIZE = 140 * 1024 * 1024      # 140MB，在线版硬限制
MAX_PATCH_ZIP_SIZE = 90 * 1024 * 1024    # 90MB，回填补丁包硬限制
TEMP_PREFIX = "unity_tool_"

LIGHT_EDITABLE_TYPES = {"MonoBehaviour", "TextAsset", "Texture2D", "Sprite", "GameObject", "Material"}
JSON_LIKE_TYPES = {"MonoBehaviour", "TextAsset", "GameObject", "Material", "AnimationClip", "AnimatorController"}
IMAGE_TYPES = {"Texture2D", "Sprite"}
DEFAULT_RECOMMENDED_TYPES = ["MonoBehaviour", "TextAsset"]
DEFAULT_PATCH_TYPES = ["MonoBehaviour", "TextAsset"]
DEFAULT_IMAGE_TYPES = ["Texture2D", "Sprite"]

# 常见 Unity PPtr 字段名：回填前必须是 dict，不能是 JSON 字符串
PPTR_FIELD_KEYS = {
    "m_Script",
    "m_GameObject",
    "m_Father",
    "m_Controller",
    "m_Mesh",
    "m_Material",
    "m_Font",
    "m_Texture",
    "m_Sprite",
    "m_Parent",
    "m_Prefab",
    "m_PrefabInstance",
    "m_PrefabAsset",
    "m_CorrespondingSourceObject",
}


class ClientFacingError(Exception):
    """用户输入 / 补丁内容问题 → HTTP 4xx，避免整页 500。"""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = int(status)


def reject_if_too_large(max_size, label="文件"):
    content_length = request.content_length
    if content_length and content_length > max_size:
        mb = max_size // 1024 // 1024
        raise ClientFacingError(
            f"{label}过大。在线版当前限制约 {mb}MB；更大的 Bundle 建议使用本地版或仅上传补丁包。",
            status=413,
        )


def save_upload_to_workdir(upload, workdir, fallback_name="upload.bin"):
    filename = safe_name(upload.filename or fallback_name)
    path = os.path.join(workdir, filename)
    upload.save(path)
    return path


def cleanup_old_temp(max_age_seconds=30 * 60):
    root = tempfile.gettempdir()
    now = os.path.getmtime(root) if os.path.exists(root) else 0

    for name in os.listdir(root):
        if not name.startswith(TEMP_PREFIX):
            continue

        path = os.path.join(root, name)
        try:
            age = os.path.getmtime(path)
            # 用 time 模块也行，这里避免额外导入；只要能清掉旧目录即可。
            import time
            if time.time() - age > max_age_seconds:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    os.remove(path)
        except Exception:
            pass


def register_cleanup(path):
    @after_this_request
    def cleanup(response):
        try:
            if os.path.isdir(path):
                shutil.rmtree(path, ignore_errors=True)
            elif os.path.exists(path):
                os.remove(path)
            gc.collect()
        except Exception:
            pass
        return response


def read_text_from_zip(zf, path):
    raw_bytes = zf.read(path)

    for enc in ['utf-8-sig', 'gbk', 'utf-16', 'utf-8']:
        try:
            return raw_bytes.decode(enc)
        except UnicodeDecodeError:
            continue

    return raw_bytes.decode('utf-8', errors='ignore')


def safe_name(name):
    if not name:
        return "Unnamed"

    name = str(name)
    name = re.sub(r'[\\/:*?"<>|]', '_', name)
    name = name.strip()

    return name or "Unnamed"


def is_ignored_zip_entry(name):
    normalized = name.replace('\\', '/')
    file_name = normalized.split('/')[-1]

    return (
        not file_name
        or '__MACOSX' in normalized
        or file_name.startswith('.')
        or file_name.endswith('.bak')
    )


# ==================== 格式处理 ====================

class FormatManager:
    @staticmethod
    def to_csv(data_dict):
        output = io.StringIO()
        writer = csv.writer(output, lineterminator='\n')

        if isinstance(data_dict, dict):
            for key, value in data_dict.items():
                val_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                writer.writerow([key, val_str])

        return output.getvalue().encode('utf-8-sig')

    @staticmethod
    def from_csv(csv_text):
        result = {}
        stream = io.StringIO(csv_text)
        reader = csv.reader(stream)

        for row in reader:
            if len(row) >= 2 and row[0].strip():
                key = row[0].strip()
                val = row[1]

                if isinstance(val, str) and (val.startswith('{') or val.startswith('[')):
                    try:
                        val = json.loads(val)
                    except Exception:
                        pass

                result[key] = val

        return result


# 仅对「字符串里嵌 JSON」的字段做 expand/collapse。
#
# m_Script 有双语义，不可按键名一刀切：
# - MonoBehaviour：PPtr 字典 {m_FileID, m_PathID} —— 禁止 stringify
#   （stringify 会导致 save_typetree 报 'str' object has no attribute 'm_FileID'）
# - TextAsset：实际文本内容，常为整段 pretty JSON（含真实 \r\n）—— 必须 expand
#   否则 json.dumps 会把正文二次转义成 "{\\r\\n \\"1\\": ...}" 一整行，无法正常换行编辑
#
# 判定顺序：先 is_pptr_like(v) 跳过引用；仅当值为 JSON 文本字符串时才 expand/collapse。
STRING_EMBEDDED_JSON_KEYS = {
    "m_Data",
    "m_RawData",
    "m_ScriptText",
    "m_Script",  # TextAsset 文本；MonoBehaviour 时因 is_pptr_like 被跳过
    "jsonData",
    "JsonData",
    "dataJson",
    "rawJson",
    "script",
    "text",
}


def is_pptr_like(value):
    """识别 Unity PPtr / FileID-PathID 引用，禁止被当成 JSON 字符串折叠。"""
    if not isinstance(value, dict):
        return False
    keys = set(value.keys())
    if not keys:
        return False
    allowed = {"m_FileID", "m_PathID", "m_FileId", "m_PathId"}
    return keys.issubset(allowed) and (
        "m_FileID" in value or "m_FileId" in value or "m_PathID" in value or "m_PathId" in value
    )


def looks_like_json_text(text):
    if not isinstance(text, str):
        return False
    s = text.strip()
    if not s:
        return False
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))


def detect_json_newline(text):
    """从原始嵌入 JSON 文本推断换行风格，collapse 时尽量还原。"""
    if not isinstance(text, str):
        return "\n"
    # 优先检测真实 CRLF / CR；再检测已被写成字面 \\r\\n 的情况（极少见）
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text and "\n" not in text:
        return "\r"
    return "\n"


def dumps_embedded_json(value, process_strategy="auto", newline="\n"):
    """
    把 expand 后的对象压回字符串。
    - auto：紧凑单行，体积小、稳定
    - 其它（raw 等）：保留 indent=4 可读格式，并按原文本换行风格输出
    """
    if process_strategy == "auto":
        body = json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    else:
        body = json.dumps(value, indent=4, ensure_ascii=False)

    if newline == "\r\n":
        # json.dumps 只产出 \n，按原 TextAsset 习惯还原 CRLF
        body = body.replace("\r\n", "\n").replace("\n", "\r\n")
    elif newline == "\r":
        body = body.replace("\r\n", "\n").replace("\n", "\r")
    return body


def parse_embedded_json(text, process_strategy="auto"):
    cleaned = clean_json_string(text) if process_strategy == "auto" else text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            return json5.loads(cleaned)
        except Exception:
            return text


def _snippet_around(text, pos, radius=48):
    """截取错误位置附近文本，方便用户定位。"""
    if not isinstance(text, str) or pos is None or pos < 0:
        return ""
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    chunk = text[start:end].replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{chunk}{suffix}"


def format_json_parse_error(exc, raw_text, source_label="JSON"):
    """把 JSONDecodeError / json5 异常转成可读中文说明。"""
    msg = str(exc) if exc is not None else "未知解析错误"
    line = getattr(exc, "lineno", None)
    col = getattr(exc, "colno", None)
    pos = getattr(exc, "pos", None)

    # json5 有时只给 message，尽量从文案里抠位置
    if line is None and isinstance(msg, str):
        m = re.search(r"line\s+(\d+)", msg, re.I)
        if m:
            line = int(m.group(1))
        m = re.search(r"column\s+(\d+)", msg, re.I)
        if m:
            col = int(m.group(1))

    parts = [f"{source_label} 解析失败"]
    if line is not None:
        loc = f"第 {line} 行"
        if col is not None:
            loc += f"、第 {col} 列"
        parts.append(loc)
    parts.append(msg)

    hint = (
        "请检查：1) 是否漏了逗号/括号；2) 属性名是否都用双引号；"
        "3) 是否残留尾逗号或注释（可改用 auto 模式清洗）；"
        "4) 是否误把 PNG/二进制当成 JSON。"
    )
    snippet = _snippet_around(raw_text, pos) if pos is not None else ""
    if not snippet and line is not None and isinstance(raw_text, str):
        lines = raw_text.splitlines()
        if 1 <= line <= len(lines):
            snippet = lines[line - 1].strip()[:96]

    body = "：".join(parts[:1]) + ("（" + "，".join(parts[1:]) + "）" if len(parts) > 1 else "")
    if snippet:
        body += f" 片段：{snippet}"
    body += f" —— {hint}"
    return body


def parse_patch_json(raw_text, process_mode="auto", source_label="JSON"):
    """
    解析用户补丁中的 typetree JSON，严格校验后返回 dict。
    失败一律抛 ClientFacingError（HTTP 400），不走 500。
    """
    if raw_text is None:
        raise ClientFacingError(f"{source_label} 内容为空。")

    if not isinstance(raw_text, str):
        try:
            raw_text = raw_text.decode("utf-8")
        except Exception:
            raise ClientFacingError(f"{source_label} 不是合法的文本内容（编码无法识别）。")

    # 二进制误传：在 clean 之前检查原始内容（clean 会去掉控制字符）
    raw_sample = raw_text[:240]
    if "\x00" in raw_sample or sum(
        1 for c in raw_sample if ord(c) < 32 and c not in "\t\n\r"
    ) > 8:
        raise ClientFacingError(
            f"{source_label} 看起来像二进制数据，不是 JSON 文本。"
            "请确认扩展名与导出格式，或重新从本站解包后再编辑。"
        )

    cleaned = clean_json_string(raw_text) if process_mode == "auto" else raw_text
    text = cleaned.strip() if isinstance(cleaned, str) else ""
    if not text:
        raise ClientFacingError(
            f"{source_label} 为空或仅含空白/不可见字符。请确认 ZIP 内该文件未损坏。"
        )

    starts_obj = text.startswith("{")
    starts_arr = text.startswith("[")
    ends_obj = text.rstrip().endswith("}")
    ends_arr = text.rstrip().endswith("]")
    if not ((starts_obj and ends_obj) or (starts_arr and ends_arr)):
        head = text[:40].replace("\n", " ")
        if starts_obj or starts_arr:
            raise ClientFacingError(
                f"{source_label} 疑似被截断或不完整（有开头括号但缺少对应结尾）。"
                f"当前开头：{head!r}。请重新保存 JSON 后再打包。"
            )
        raise ClientFacingError(
            f"{source_label} 必须以 {{...}} 或 [...] 包裹（当前开头：{head!r}）。"
            "常见原因：文件截断、编码错误、或误传了非 JSON 文件。"
        )

    parsed = None
    last_err = None
    for loader in (json.loads, json5.loads):
        try:
            parsed = loader(text)
            break
        except Exception as e:
            last_err = e
            parsed = None

    if parsed is None:
        raise ClientFacingError(format_json_parse_error(last_err, text, source_label))

    if not isinstance(parsed, dict):
        raise ClientFacingError(
            f"{source_label} 根节点必须是对象 {{...}}（Unity typetree），"
            f"当前是 {type(parsed).__name__}。"
            "数组/字符串/数字无法 save_typetree，请使用本站解包导出的 JSON。"
        )

    return parsed


def collect_typetree_shape_issues(tree, obj_type_name=None):
    """
    回填前数据结构体检。
    返回 (hard_errors: list[str], warnings: list[str])。
    hard_errors 会阻断注入；warnings 仅用于预检提示。
    """
    hard = []
    warnings = []

    if not isinstance(tree, dict):
        hard.append("根节点不是对象")
        return hard, warnings

    if not tree:
        hard.append("JSON 对象为空，无法作为 typetree 写回")
        return hard, warnings

    # 关键类型启发式：至少应有 m_Name / m_Script / m_GameObject 之一
    common = {"m_Name", "m_Script", "m_GameObject", "m_PathID", "m_FileID"}
    if not (set(tree.keys()) & common) and len(tree) < 2:
        warnings.append("字段过少且缺少常见 Unity 键，可能不是本站解包产物")

    def walk(node, path=""):
        if isinstance(node, dict):
            # 完整 PPtr 被错误写成非 dict
            if is_pptr_like(node):
                return

            for k, v in node.items():
                p = f"{path}.{k}" if path else k

                # MonoBehaviour 的 m_Script 必须是 PPtr dict；TextAsset 的 m_Script 是字符串
                if k == "m_Script" and obj_type_name == "MonoBehaviour":
                    if isinstance(v, str):
                        if looks_like_json_text(v):
                            try:
                                restored = json.loads(clean_json_string(v))
                            except Exception:
                                try:
                                    restored = json5.loads(clean_json_string(v))
                                except Exception:
                                    restored = None
                            if not is_pptr_like(restored):
                                hard.append(
                                    f"{p} 在 MonoBehaviour 中必须是 PPtr "
                                    "{m_FileID, m_PathID}，当前字符串无法还原为引用"
                                )
                        else:
                            hard.append(
                                f"{p} 在 MonoBehaviour 中必须是 PPtr 字典，不能是普通字符串"
                            )
                    elif isinstance(v, dict) and not is_pptr_like(v):
                        # expand 后的嵌入 JSON 对象：对 MonoBehaviour 非法
                        if not (
                            set(v.keys()) <= {"m_FileID", "m_PathID", "m_FileId", "m_PathId"}
                        ):
                            hard.append(
                                f"{p} 在 MonoBehaviour 中应为 PPtr 引用，"
                                "当前是普通对象（疑似把 TextAsset 正文结构写进了 MonoBehaviour）"
                            )

                if k in PPTR_FIELD_KEYS and k != "m_Script" and isinstance(v, str) and looks_like_json_text(v):
                    try:
                        restored = json.loads(clean_json_string(v))
                    except Exception:
                        restored = None
                    if restored is not None and not is_pptr_like(restored):
                        warnings.append(f"{p} 字符串不像合法 PPtr，写回可能失败")

                if isinstance(v, (dict, list)):
                    walk(v, p)

        elif isinstance(node, list):
            for i, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}[{i}]")

    walk(tree)
    return hard, warnings


def prepare_typetree_for_inject(new_tree, process_mode="auto", obj_type_name=None, source_label="JSON"):
    """
    collapse 嵌入 JSON + 还原误导出的 PPtr 字符串，并做结构校验。
    返回可 save_typetree 的 dict。

    阻断性检查只看「restore + collapse 之后」的最终树，避免把仍可自动修复的
    PPtr 字符串误判为 hard error。
    """
    if not isinstance(new_tree, dict):
        raise ClientFacingError(f"{source_label} 根节点必须是对象。")

    # 先 restore，再 collapse 嵌入 JSON，最后再 restore 一轮（嵌套历史坏导出）
    tree = restore_pptr_fields(new_tree)
    collapsed = transform_json_tree(tree, mode="collapse", process_strategy=process_mode)
    collapsed = restore_pptr_fields(collapsed)

    hard, _warnings = collect_typetree_shape_issues(collapsed, obj_type_name=obj_type_name)
    if hard:
        raise ClientFacingError(
            f"{source_label} 数据结构不匹配，已中止注入：{hard[0]}"
            + (f"（另有 {len(hard) - 1} 项）" if len(hard) > 1 else "")
        )

    return collapsed


def inject_typetree_to_object(obj, new_tree, process_mode="auto", source_label="JSON"):
    """collapse → 校验 → save_typetree，失败给出友好原因。"""
    type_name = getattr(getattr(obj, "type", None), "name", None)
    collapsed = prepare_typetree_for_inject(
        new_tree,
        process_mode=process_mode,
        obj_type_name=type_name,
        source_label=source_label,
    )

    try:
        obj.save_typetree(collapsed)
        return
    except Exception as save_err:
        collapsed = restore_pptr_fields(collapsed)
        try:
            obj.save_typetree(collapsed)
            return
        except Exception:
            err_s = str(save_err)
            hint = ""
            if "m_FileID" in err_s or "m_PathID" in err_s or "attribute" in err_s.lower():
                hint = (
                    " 常见原因：PPtr 字段（如 m_Script）被写成了字符串或类型不对；"
                    "请用本站重新解包，只改业务字段后再回填。"
                )
            elif "type" in err_s.lower() or "expected" in err_s.lower():
                hint = " 常见原因：字段类型与原始 Bundle 不一致（例如数字写成了字符串）。"
            raise ClientFacingError(
                f"{source_label} 写入 Bundle 失败（save_typetree）：{save_err}.{hint}"
            ) from save_err


def transform_json_tree(tree, mode="expand", process_strategy="auto", _newline_hints=None):
    """
    expand：把「字符串形式的嵌入 JSON」解析成对象，便于正常换行编辑。
    collapse：把上述字段重新压回字符串，再 save_typetree。

    重要：
    - 任意 PPtr 形态字段（含 MonoBehaviour 的 m_Script dict）绝不 stringify
    - TextAsset 的 m_Script 字符串 JSON 会 expand 成对象（导出带真实换行）
    - 非 STRING_EMBEDDED_JSON_KEYS 的 dict/list 只递归，不 stringify
    """
    if _newline_hints is None:
        _newline_hints = {}

    if isinstance(tree, dict):
        for k, v in list(tree.items()):
            # 只按值形态保护 PPtr，不再按键名硬跳过 m_Script
            if is_pptr_like(v):
                continue

            if k in STRING_EMBEDDED_JSON_KEYS:
                if mode == "expand" and isinstance(v, str) and looks_like_json_text(v):
                    # 记录原换行风格，供同树 collapse 时还原（同一次调用链内有效）
                    _newline_hints[id(tree), k] = detect_json_newline(v)
                    parsed = parse_embedded_json(v, process_strategy)
                    tree[k] = parsed
                    if isinstance(parsed, (dict, list)):
                        transform_json_tree(parsed, mode, process_strategy, _newline_hints)

                elif mode == "collapse" and isinstance(v, (dict, list)):
                    # PPtr 误入可折叠键时也不折叠
                    if is_pptr_like(v):
                        continue
                    transform_json_tree(v, mode, process_strategy, _newline_hints)
                    newline = _newline_hints.get((id(tree), k), "\n")
                    # TextAsset 正文：raw 模式保留 pretty+原换行；auto 紧凑（语义等价）
                    # 若值为「非 PPtr 的普通对象」，一律按嵌入 JSON 字符串写回
                    tree[k] = dumps_embedded_json(v, process_strategy, newline=newline)

                elif isinstance(v, (dict, list)):
                    transform_json_tree(v, mode, process_strategy, _newline_hints)

            elif isinstance(v, (dict, list)):
                transform_json_tree(v, mode, process_strategy, _newline_hints)

    elif isinstance(tree, list):
        for item in tree:
            if isinstance(item, (dict, list)):
                transform_json_tree(item, mode, process_strategy, _newline_hints)

    return tree


def restore_pptr_fields(tree):
    """
    兼容旧版错误导出：曾把 m_Script 等 PPtr collapse 成 JSON 字符串。
    回填前把可识别的 PPtr 字符串还原为 dict，避免 save_typetree 失败。
    """
    if isinstance(tree, dict):
        for k, v in list(tree.items()):
            if isinstance(v, str) and (k in PPTR_FIELD_KEYS or k.startswith("m_")) and looks_like_json_text(v):
                try:
                    parsed = json.loads(clean_json_string(v))
                except Exception:
                    try:
                        parsed = json5.loads(clean_json_string(v))
                    except Exception:
                        parsed = None
                if is_pptr_like(parsed):
                    tree[k] = parsed
                    continue
            if isinstance(v, (dict, list)):
                restore_pptr_fields(v)
    elif isinstance(tree, list):
        for item in tree:
            if isinstance(item, (dict, list)):
                restore_pptr_fields(item)

    return tree


# ==================== Bundle 分析 ====================

def guess_export_modes(type_name):
    if type_name in IMAGE_TYPES:
        return ["png"]
    if type_name in JSON_LIKE_TYPES or type_name in LIGHT_EDITABLE_TYPES:
        return ["json", "csv"]
    return []


def get_object_display_name(obj):
    try:
        if obj.type.name in ["Texture2D", "Sprite"]:
            data = obj.read()
            return getattr(data, 'name', '') or f"Object_{obj.path_id}"

        tree = obj.read_typetree()
        if isinstance(tree, dict):
            return tree.get("m_Name") or f"Object_{obj.path_id}"

    except Exception:
        pass

    return f"Object_{obj.path_id}"


def inspect_env_light(env):
    objects = []
    type_counts = {}

    for obj in env.objects:
        type_name = obj.type.name
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

        objects.append({
            "path_id": str(obj.path_id),
            "type": type_name,
            "name": f"Object_{obj.path_id}",
            "editable": type_name in LIGHT_EDITABLE_TYPES,
            "export_modes": guess_export_modes(type_name),
            "depth": "fast"
        })

    return {
        "total_objects": len(objects),
        "type_counts": type_counts,
        "objects": objects,
        "depth": "fast"
    }


def inspect_env(env):
    objects = []
    type_counts = {}

    for obj in env.objects:
        type_name = obj.type.name
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

        item = {
            "path_id": str(obj.path_id),
            "type": type_name,
            "name": get_object_display_name(obj),
            "editable": False,
            "export_modes": [],
            "depth": "deep"
        }

        if type_name in ["Texture2D", "Sprite"]:
            item["editable"] = True
            item["export_modes"] = ["png"]

        else:
            try:
                tree = obj.read_typetree()
                if tree:
                    item["editable"] = True
                    item["export_modes"] = ["json", "csv"]
                else:
                    item["export_modes"] = []
            except Exception:
                item["export_modes"] = []

        objects.append(item)

    return {
        "total_objects": len(objects),
        "type_counts": type_counts,
        "objects": objects,
        "depth": "deep"
    }


# ==================== ZIP 补丁分析 / 预检 ====================

def build_zip_patch_maps(zf):
    zip_file_map = {}
    fallback_map = {}
    index_data = {}
    entries = []

    for name in zf.namelist():
        if is_ignored_zip_entry(name):
            continue

        normalized_name = name.replace('\\', '/')
        file_name_only = normalized_name.split('/')[-1]

        zip_file_map[file_name_only] = normalized_name
        entries.append(normalized_name)

        match = re.search(r'_(\d+)\.(json|csv|png|dat)$', file_name_only, re.IGNORECASE)
        if match:
            fallback_map[match.group(1)] = normalized_name

        if file_name_only == '_index.json':
            try:
                raw_index = read_text_from_zip(zf, name)
                cleaned_index = clean_json_string(raw_index)
                try:
                    index_data = json.loads(cleaned_index)
                except json.JSONDecodeError:
                    index_data = json5.loads(cleaned_index)
            except ClientFacingError:
                raise
            except Exception as e:
                raise ClientFacingError(
                    format_json_parse_error(e, raw_index if 'raw_index' in locals() else '', "_index.json")
                ) from e

            if not isinstance(index_data, dict):
                raise ClientFacingError(
                    "_index.json 根节点必须是对象：{ \"path_id\": \"相对路径/文件名.json\", ... }"
                )

            # 规范化：值统一为字符串路径
            bad_keys = [k for k, v in index_data.items() if not isinstance(v, str) or not str(v).strip()]
            if bad_keys:
                sample = ", ".join(str(k) for k in bad_keys[:5])
                raise ClientFacingError(
                    f"_index.json 中有 {len(bad_keys)} 个无效条目（值必须是非空路径字符串），"
                    f"例如键：{sample}"
                )

    return zip_file_map, fallback_map, index_data, entries


def find_patch_for_object(obj, zip_file_map, fallback_map, index_data):
    path_id_str = str(obj.path_id)
    actual_zip_path = None
    expected_filename = None
    match_source = None

    if index_data and path_id_str in index_data:
        expected_filename = index_data[path_id_str].replace('\\', '/').split('/')[-1]
        actual_zip_path = zip_file_map.get(expected_filename)
        match_source = "_index.json"

    if not actual_zip_path and path_id_str in fallback_map:
        actual_zip_path = fallback_map[path_id_str]
        expected_filename = actual_zip_path.split('/')[-1]
        match_source = "filename_path_id"

    return actual_zip_path, expected_filename, match_source


def validate_patch_against_bundle(env, zf, process_mode='auto', validate_level='fast', repack_mode='patch'):
    zip_file_map, fallback_map, index_data, entries = build_zip_patch_maps(zf)

    report = {
        "ok": True,
        "summary": {
            "zip_files": len(entries),
            "matched": 0,
            "will_modify": 0,
            "warnings": 0,
            "errors": 0
        },
        "items": [],
        "unmatched_files": [],
        "has_index": bool(index_data),
        "validate_level": validate_level,
        "repack_mode": repack_mode
    }

    if repack_mode == 'patch' and len(entries) > 200:
        report["summary"]["warnings"] += 1
        report["items"].append({
            "path_id": "-",
            "type": "ZIP",
            "name": "补丁包体积提示",
            "file": "-",
            "zip_path": "-",
            "match_source": "repack_mode",
            "status": "warning",
            "level": "warning",
            "message": "当前 ZIP 文件数量较多，看起来像完整导出包。在线版建议只保留修改过的文件和 _index.json。"
        })

    matched_zip_paths = set()

    for obj in env.objects:
        actual_zip_path, expected_filename, match_source = find_patch_for_object(
            obj,
            zip_file_map,
            fallback_map,
            index_data
        )

        if not actual_zip_path:
            continue

        matched_zip_paths.add(actual_zip_path)

        item = {
            "path_id": str(obj.path_id),
            "type": obj.type.name,
            "name": f"Object_{obj.path_id}" if validate_level == 'fast' else get_object_display_name(obj),
            "file": expected_filename,
            "zip_path": actual_zip_path,
            "match_source": match_source,
            "status": "ok",
            "level": "safe",
            "message": "文件名与对象类型匹配，可回填"
        }

        lower_name = expected_filename.lower()

        try:
            if lower_name.endswith('.png'):
                if obj.type.name not in ["Texture2D", "Sprite"]:
                    item["status"] = "error"
                    item["level"] = "danger"
                    item["message"] = "PNG 只能回填到 Texture2D 或 Sprite"
                elif validate_level == 'full':
                    with zf.open(actual_zip_path) as fp:
                        img = Image.open(fp)
                        img.verify()
                    item["message"] = "图片格式有效，可回填"

            elif lower_name.endswith('.json'):
                if validate_level == 'full':
                    raw_json_str = read_text_from_zip(zf, actual_zip_path)
                    try:
                        parsed = parse_patch_json(
                            raw_json_str,
                            process_mode=process_mode,
                            source_label=expected_filename,
                        )
                    except ClientFacingError as ce:
                        item["status"] = "error"
                        item["level"] = "danger"
                        item["message"] = str(ce)
                    else:
                        hard, soft = collect_typetree_shape_issues(
                            parsed, obj_type_name=obj.type.name
                        )
                        # collapse 路径再体检一次（更接近真实注入）
                        try:
                            prepare_typetree_for_inject(
                                parsed,
                                process_mode=process_mode,
                                obj_type_name=obj.type.name,
                                source_label=expected_filename,
                            )
                        except ClientFacingError as ce:
                            hard.append(str(ce))

                        if hard:
                            item["status"] = "error"
                            item["level"] = "danger"
                            item["message"] = hard[0]
                        elif soft:
                            item["status"] = "warning"
                            item["level"] = "warning"
                            item["message"] = soft[0]
                        else:
                            item["message"] = "JSON 格式与数据结构有效，可回填"
                else:
                    # fast：仅做轻量扩展名/类型提示，不读全文
                    item["message"] = "文件名与对象匹配（快速预检未解析 JSON 正文）"

            elif lower_name.endswith('.csv'):
                if validate_level == 'full':
                    csv_text = read_text_from_zip(zf, actual_zip_path)
                    parsed = FormatManager.from_csv(csv_text)

                    if not parsed or not isinstance(parsed, dict):
                        item["status"] = "warning"
                        item["level"] = "warning"
                        item["message"] = "CSV 未解析出有效字段（需要 键,值 两列）"
                    else:
                        hard, soft = collect_typetree_shape_issues(
                            parsed, obj_type_name=obj.type.name
                        )
                        if hard:
                            item["status"] = "error"
                            item["level"] = "danger"
                            item["message"] = hard[0]
                        elif soft:
                            item["status"] = "warning"
                            item["level"] = "warning"
                            item["message"] = soft[0]
                        else:
                            item["message"] = "CSV 可解析，可回填"

            elif lower_name.endswith('.dat'):
                item["status"] = "warning"
                item["level"] = "danger"
                item["message"] = "RAW/DAT 属于高危回填，可能导致资源损坏"

            else:
                item["status"] = "warning"
                item["level"] = "warning"
                item["message"] = "未知扩展名，将按 RAW 处理"

        except ClientFacingError as e:
            item["status"] = "error"
            item["level"] = "danger"
            item["message"] = str(e)
        except Exception as e:
            item["status"] = "error"
            item["level"] = "danger"
            item["message"] = f"预检该项时出错：{e}"

        if item["status"] == "error":
            report["summary"]["errors"] += 1
            report["ok"] = False
        elif item["status"] == "warning":
            report["summary"]["warnings"] += 1

        report["summary"]["matched"] += 1
        report["summary"]["will_modify"] += 1
        report["items"].append(item)

    for path in entries:
        if path not in matched_zip_paths and not path.endswith('_index.json'):
            report["unmatched_files"].append(path)

    if report["unmatched_files"]:
        report["summary"]["warnings"] += len(report["unmatched_files"])

    if report["summary"]["will_modify"] == 0:
        report["ok"] = False
        report["summary"]["errors"] += 1
        report["items"].append({
            "path_id": "-",
            "type": "-",
            "name": "-",
            "file": "-",
            "zip_path": "-",
            "match_source": "-",
            "status": "error",
            "level": "danger",
            "message": "没有检测到任何可回填对象，请检查 ZIP 是否来自当前 Bundle 的解包结果"
        })

    return report


# ==================== 解包策略 ====================

def parse_bool_form(name, default=False):
    val = request.form.get(name)
    if val is None:
        return default
    return str(val).lower() in {"1", "true", "yes", "on"}


def get_unpack_policy():
    preset = request.form.get('preset', 'recommended')
    target_format = request.form.get('format', 'json')
    process_mode = request.form.get('mode', 'auto')

    selected_types = request.form.getlist('types')
    include_images = parse_bool_form('include_images', False)
    include_index = parse_bool_form('include_index', True)

    # RAW 导出入口已下线，统一走 JSON/CSV/PNG 安全通道
    if target_format not in {'json', 'csv'}:
        target_format = 'json'

    if preset == 'recommended':
        selected_types = DEFAULT_RECOMMENDED_TYPES
        target_format = 'json'
        include_images = False
        include_index = True
    elif preset == 'patch':
        selected_types = DEFAULT_PATCH_TYPES
        target_format = 'json'
        include_images = False
        include_index = True
    elif preset == 'images':
        selected_types = DEFAULT_IMAGE_TYPES
        target_format = 'json'
        include_images = True
        include_index = True
    elif preset == 'advanced':
        if not selected_types:
            selected_types = DEFAULT_RECOMMENDED_TYPES
    else:
        # 兼容旧前端仍提交 raw 等未知 preset
        preset = 'recommended'
        selected_types = DEFAULT_RECOMMENDED_TYPES
        target_format = 'json'
        include_images = False
        include_index = True

    return {
        "preset": preset,
        "target_format": target_format,
        "process_mode": process_mode,
        "selected_types": selected_types,
        "include_images": include_images,
        "include_index": include_index,
    }


def should_export_object(obj, policy):
    selected_types = set(policy["selected_types"])
    if '__all__' in selected_types:
        return True
    return obj.type.name in selected_types


def export_image_object(obj, zf, workdir, index_data):
    data = obj.read()
    name = safe_name(getattr(data, 'name', '') or f"Object_{obj.path_id}")
    file_name = f"Images/{name}_{obj.path_id}.png"

    # PNG 编码先落到磁盘，再写入 ZIP，避免 BytesIO + getvalue 的双份内存复制。
    image_path = os.path.join(workdir, f"image_{obj.path_id}.png")
    data.image.save(image_path, 'PNG')
    zf.write(image_path, file_name)
    index_data[str(obj.path_id)] = file_name


def export_typetree_object(obj, zf, index_data, policy):
    tree = obj.read_typetree()
    if not tree:
        return False

    tree = transform_json_tree(tree, mode='expand', process_strategy=policy["process_mode"])
    name = safe_name(tree.get("m_Name", f"Object_{obj.path_id}")) if isinstance(tree, dict) else f"Object_{obj.path_id}"
    base_name = f"{obj.type.name}/{name}_{obj.path_id}"

    if policy["target_format"] == 'csv':
        zf.writestr(f"{base_name}.csv", FormatManager.to_csv(tree))
        index_data[str(obj.path_id)] = f"{base_name}.csv"
    else:
        content = json.dumps(tree, indent=4, ensure_ascii=False).encode('utf-8')
        zf.writestr(f"{base_name}.json", content)
        index_data[str(obj.path_id)] = f"{base_name}.json"

    return True


# ==================== 页面 ====================

@unity_bp.route('/unity')
def index():
    return render_template('tab_unity.html', current_tab='unity')


# ==================== 只分析 Bundle ====================

@unity_bp.route('/unity/inspect', methods=['POST'])
def inspect_bundle():
    lock_response = acquire_unity_lock(json_response=True)
    if lock_response:
        return lock_response

    workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)

    try:
        cleanup_old_temp()
        reject_if_too_large(MAX_BUNDLE_SIZE, "Bundle 文件")
        file = request.files.get('bundle')
        inspect_depth = request.form.get('inspect_depth', 'fast')

        if not file:
            return jsonify({"success": False, "error": "请选择 Bundle 文件"}), 400

        bundle_path = save_upload_to_workdir(file, workdir, "bundle")
        try:
            env = UnityPy.load(bundle_path)
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"无法解析 Bundle，请确认是完整的 Unity AssetBundle。详情：{e}",
            }), 400

        report = inspect_env_light(env) if inspect_depth == 'fast' else inspect_env(env)

        return jsonify({
            "success": True,
            "filename": file.filename,
            "report": report
        })

    except ClientFacingError as e:
        return jsonify({"success": False, "error": str(e)}), getattr(e, "status", 400)
    except Exception as e:
        return jsonify({"success": False, "error": f"分析失败：{e}"}), 500
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        gc.collect()
        release_unity_lock()


# ==================== 解包导出 ====================

@unity_bp.route('/unpack', methods=['POST'])
def unpack():
    lock_response = acquire_unity_lock(json_response=False)
    if lock_response:
        return lock_response

    workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)

    try:
        cleanup_old_temp()
        reject_if_too_large(MAX_BUNDLE_SIZE, "Bundle 文件")
        file = request.files.get('bundle')

        if not file:
            return render_template('error.html', msg="请选择文件。"), 400

        policy = get_unpack_policy()
        bundle_path = save_upload_to_workdir(file, workdir, "bundle")
        output_zip_path = os.path.join(workdir, f"Unpacked_{safe_name(file.filename)}.zip")

        env = UnityPy.load(bundle_path)
        index_data = {}
        exported_count = 0
        skipped_count = 0
        failed_count = 0

        with zipfile.ZipFile(output_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for obj in env.objects:
                if not should_export_object(obj, policy):
                    skipped_count += 1
                    continue

                try:
                    if obj.type.name in IMAGE_TYPES:
                        if policy["include_images"]:
                            export_image_object(obj, zf, workdir, index_data)
                            exported_count += 1
                        else:
                            skipped_count += 1
                        continue

                    if export_typetree_object(obj, zf, index_data, policy):
                        exported_count += 1
                    else:
                        skipped_count += 1

                except Exception:
                    failed_count += 1

            if policy["include_index"]:
                zf.writestr("_index.json", json.dumps(index_data, indent=4, ensure_ascii=False))

            zf.writestr("_export_summary.json", json.dumps({
                "preset": policy["preset"],
                "format": policy["target_format"],
                "selected_types": policy["selected_types"],
                "include_images": policy["include_images"],
                "exported_count": exported_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count
            }, indent=4, ensure_ascii=False))

        if exported_count == 0:
            shutil.rmtree(workdir, ignore_errors=True)
            return _client_error("没有导出任何对象。请切换为高级自定义，或选择更多对象类型。", 400)

        register_cleanup(workdir)
        return send_file(
            output_zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"Unpacked_{safe_name(file.filename)}.zip"
        )

    except ClientFacingError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return _client_error(str(e), getattr(e, "status", 400))
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return _client_error(f"解包失败: {e}", 500)
    finally:
        release_unity_lock()


# ==================== 回填预检 ====================

@unity_bp.route('/unity/validate-repack', methods=['POST'])
def validate_repack():
    lock_response = acquire_unity_lock(json_response=True)
    if lock_response:
        return lock_response

    workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)

    try:
        cleanup_old_temp()
        reject_if_too_large(MAX_BUNDLE_SIZE + MAX_PATCH_ZIP_SIZE, "上传内容")
        orig_file = request.files.get('original_bundle')
        mod_zip = request.files.get('modified_zip')
        process_mode = request.form.get('mode', 'auto')
        validate_level = request.form.get('validate_level', 'fast')
        repack_mode = request.form.get('repack_mode', 'patch')

        if not orig_file or not mod_zip:
            return jsonify({"success": False, "error": "缺少原始 Bundle 或修改后的 ZIP"}), 400

        # 基础文件名校验，尽早给友好提示
        zip_name = (mod_zip.filename or "").lower()
        if zip_name and not (
            zip_name.endswith(".zip") or zip_name.endswith(".unity3d.zip")
        ):
            # 不强制扩展名（部分浏览器不带后缀），仅作软提示记录
            pass

        orig_path = save_upload_to_workdir(orig_file, workdir, "original_bundle")
        zip_path = save_upload_to_workdir(mod_zip, workdir, "modified.zip")

        try:
            env = UnityPy.load(orig_path)
        except Exception as e:
            return jsonify({
                "success": False,
                "error": f"无法解析原始 Bundle，请确认文件完整且为 Unity AssetBundle。详情：{e}",
            }), 400

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                if zf.testzip() is not None:
                    return jsonify({
                        "success": False,
                        "error": "ZIP 内部有损坏的条目，请重新打包补丁后再试。",
                    }), 400
                report = validate_patch_against_bundle(
                    env,
                    zf,
                    process_mode=process_mode,
                    validate_level=validate_level,
                    repack_mode=repack_mode
                )
        except zipfile.BadZipFile:
            return jsonify({
                "success": False,
                "error": "修改包不是有效的 ZIP 文件。请使用本站解包得到的 ZIP，或用系统压缩工具重新打包。",
            }), 400

        return jsonify({"success": True, "report": report})

    except ClientFacingError as e:
        return jsonify({"success": False, "error": str(e)}), getattr(e, "status", 400)
    except Exception as e:
        return jsonify({"success": False, "error": f"预检失败：{e}"}), 500
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        gc.collect()
        release_unity_lock()


def _client_error(msg, status=400):
    """回填/解包错误：fetch 客户端返回 JSON，普通表单仍返回错误页。"""
    from extensions import _wants_json_error
    if _wants_json_error():
        return jsonify({"success": False, "error": str(msg)}), status
    return render_template("error.html", msg=str(msg)), status


def _save_bundle_bytes(env):
    """
    将 UnityPy env 序列化为 bytes。
    lz4 在个别资源上会失败，需多层回退，避免整次 repack 500。
    """
    last_err = None
    for packer in ("lz4", None):
        try:
            if packer is None:
                return env.file.save()
            return env.file.save(packer=packer)
        except Exception as e:
            last_err = e
            print(f"[repack] env.file.save(packer={packer!r}) failed: {e}")
    # 最后尝试不带关键字参数的默认路径已在上面；若仍失败则抛出
    raise Exception(f"Bundle 写出失败（lz4/默认 packer 均失败）：{last_err}")


# ==================== 正式回填 ====================

@unity_bp.route('/repack', methods=['POST'])
def repack():
    lock_response = acquire_unity_lock(json_response=False)
    if lock_response:
        return lock_response

    workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)

    try:
        cleanup_old_temp()
        reject_if_too_large(MAX_BUNDLE_SIZE + MAX_PATCH_ZIP_SIZE, "上传内容")
        orig_file = request.files.get('original_bundle')
        mod_zip = request.files.get('modified_zip')
        process_mode = request.form.get('mode', 'auto')
        repack_mode = request.form.get('repack_mode', 'patch')

        if not orig_file or not mod_zip:
            return _client_error("缺少文件！请同时上传原始 Bundle 与修改后的 ZIP。", 400)

        if not (orig_file.filename or "").strip():
            return _client_error("原始 Bundle 文件名为空，请重新选择文件。", 400)
        if not (mod_zip.filename or "").strip():
            return _client_error("修改后的 ZIP 文件名为空，请重新选择文件。", 400)

        orig_path = save_upload_to_workdir(orig_file, workdir, "original_bundle")
        zip_path = save_upload_to_workdir(mod_zip, workdir, "modified.zip")
        output_bundle_path = os.path.join(workdir, f"modded_{safe_name(orig_file.filename)}")

        # 空文件快速失败
        if os.path.getsize(orig_path) == 0:
            return _client_error("原始 Bundle 文件大小为 0，请重新上传完整文件。", 400)
        if os.path.getsize(zip_path) == 0:
            return _client_error("修改后的 ZIP 文件大小为 0，请重新上传。", 400)

        try:
            env = UnityPy.load(orig_path)
        except Exception as e:
            return _client_error(
                f"无法解析原始 Bundle，请确认文件完整且为 Unity AssetBundle。详情：{e}",
                400,
            )

        try:
            zf_ctx = zipfile.ZipFile(zip_path, 'r')
        except zipfile.BadZipFile:
            return _client_error("修改包不是有效的 ZIP 文件，请重新打包后再试。", 400)

        with zf_ctx as zf:
            # 预检改为可选手动：仅当前端显式要求时才阻断；默认直接尝试回填。
            if parse_bool_form('require_validate', False):
                validate_report = validate_patch_against_bundle(
                    env,
                    zf,
                    process_mode=process_mode,
                    validate_level='full',
                    repack_mode=repack_mode
                )

                if not validate_report["ok"]:
                    first_err = next(
                        (it.get("message") for it in validate_report.get("items", [])
                         if it.get("status") == "error"),
                        None,
                    )
                    detail = f" 首个错误：{first_err}" if first_err else ""
                    return _client_error(
                        f"预检未通过，已中止打包。错误数：{validate_report['summary']['errors']}。"
                        f"请先回到页面执行预检查看详情。{detail}",
                        400,
                    )

            zip_file_map, fallback_map, index_data, _ = build_zip_patch_maps(zf)
            modified_files_count = 0

            for obj in env.objects:
                actual_zip_path, expected_filename, _ = find_patch_for_object(
                    obj,
                    zip_file_map,
                    fallback_map,
                    index_data
                )

                if not actual_zip_path:
                    continue

                try:
                    lower_name = expected_filename.lower()

                    if lower_name.endswith('.png'):
                        if obj.type.name in ["Texture2D", "Sprite"]:
                            data = obj.read()
                            with zf.open(actual_zip_path) as img_fp:
                                try:
                                    pil_img = Image.open(img_fp).convert('RGBA')
                                except Exception as img_err:
                                    raise ClientFacingError(
                                        f"无法读取 PNG 图片：{img_err}。请确认是标准 PNG。"
                                    ) from img_err
                                data.image = pil_img
                                data.save()
                            modified_files_count += 1
                        else:
                            raise ClientFacingError(
                                f"PNG 只能回填到 Texture2D/Sprite，当前对象类型是 {obj.type.name}"
                            )

                    elif lower_name.endswith('.json'):
                        raw_json_str = read_text_from_zip(zf, actual_zip_path)
                        new_tree = parse_patch_json(
                            raw_json_str,
                            process_mode=process_mode,
                            source_label=expected_filename,
                        )
                        # 嵌入 JSON 压回字符串；PPtr 保持 dict；结构校验后 save_typetree
                        inject_typetree_to_object(
                            obj,
                            new_tree,
                            process_mode=process_mode,
                            source_label=expected_filename,
                        )
                        modified_files_count += 1

                    elif lower_name.endswith('.csv'):
                        csv_text = read_text_from_zip(zf, actual_zip_path)
                        if not csv_text or not str(csv_text).strip():
                            raise ClientFacingError(f"{expected_filename} CSV 文件为空")
                        new_tree = FormatManager.from_csv(csv_text)

                        if not isinstance(new_tree, dict) or not new_tree:
                            raise ClientFacingError(
                                f"{expected_filename} CSV 未能解析为对象字段表"
                                "（需要至少两列：字段名,值）"
                            )

                        inject_typetree_to_object(
                            obj,
                            new_tree,
                            process_mode=process_mode,
                            source_label=expected_filename,
                        )
                        modified_files_count += 1

                    else:
                        # 非 json/csv/png：高危 raw，仅在文件非空时写入
                        raw_bytes = zf.read(actual_zip_path)
                        if not raw_bytes:
                            raise ClientFacingError(f"{expected_filename} 原始数据为空，已跳过写入")
                        obj.set_raw_data(raw_bytes)
                        modified_files_count += 1

                except ClientFacingError as e:
                    # 带上文件名上下文，方便前端直接展示
                    msg = str(e)
                    if expected_filename and expected_filename not in msg:
                        msg = f"文件 [{expected_filename}]：{msg}"
                    raise ClientFacingError(msg, status=getattr(e, "status", 400)) from e
                except Exception as e:
                    raise ClientFacingError(
                        f"文件 [{expected_filename}] 注入失败：{e}"
                    ) from e

            if modified_files_count == 0:
                raise ClientFacingError(
                    "没有检测到任何可注入的补丁文件。"
                    "请检查：1) ZIP 是否来自当前 Bundle 的解包结果；"
                    "2) 是否保留 _index.json 或文件名中的 path_id；"
                    "3) 原始 Bundle 是否选错版本。"
                )

        # UnityPy 的 save 会产生完整输出；落盘返回可减少后续复制。
        # lz4 失败时回退默认 packer，避免整次 500。
        try:
            saved_bytes = _save_bundle_bytes(env)
        except MemoryError:
            gc.collect()
            raise ClientFacingError(
                "服务器内存不足，无法完成大 Bundle 写出。"
                "请改用「仅补丁」ZIP（只含修改过的对象 + _index.json），或使用本地版工具。",
                status=507,
            )
        except Exception as e:
            raise ClientFacingError(
                f"Bundle 写出失败：{e}。若仅改了少量对象，请使用补丁模式减小包体后重试。",
                status=500,
            ) from e

        with open(output_bundle_path, 'wb') as fp:
            fp.write(saved_bytes)
        del saved_bytes
        gc.collect()

        register_cleanup(workdir)
        return send_file(
            output_bundle_path,
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name=f"modded_{safe_name(orig_file.filename)}"
        )

    except ClientFacingError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return _client_error(str(e), getattr(e, "status", 400))
    except zipfile.BadZipFile:
        shutil.rmtree(workdir, ignore_errors=True)
        return _client_error("修改包不是有效的 ZIP 文件，请重新打包后再试。", 400)
    except MemoryError:
        shutil.rmtree(workdir, ignore_errors=True)
        gc.collect()
        print("[repack] MemoryError during repack")
        return _client_error(
            "服务器内存不足，打包中止。请缩小补丁包体积或稍后再试。",
            507,
        )
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        import traceback
        print(f"[repack] FAILED: {e}")
        traceback.print_exc()
        # 未知异常仍返回可读 JSON/错误页，避免裸 500 堆栈页
        return _client_error(
            f"打包未能完成：{e}。若刚编辑过 JSON，请先点「预检」确认语法与结构。",
            500,
        )
    finally:
        release_unity_lock()
