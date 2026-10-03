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
import gc
from werkzeug.exceptions import RequestEntityTooLarge
from utils import patch_limits, export_limits
from utils.patch_limits import (
    ClientFacingError, load_patch_json, check_json_tree, open_patch_zip,
)

unity_bp = Blueprint('unity', __name__)

from extensions import acquire_unity_lock, release_unity_lock

MAX_BUNDLE_SIZE = 140 * 1024 * 1024      # 140MB，在线版硬限制
MAX_PATCH_ZIP_SIZE = 90 * 1024 * 1024    # 90MB，回填补丁包硬限制
TEMP_PREFIX = "unity_tool_"

TEXT_OBJECT_TYPES = {"MonoBehaviour", "TextAsset"}

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


def reject_if_too_large(max_size, label="文件"):
    content_length = request.content_length
    if content_length and content_length > max_size:
        mb = max_size // 1024 // 1024
        raise ClientFacingError(
            f"{label}过大。在线版当前限制约 {mb}MB；更大的 Bundle 建议使用本地版或仅上传补丁包。",
            status=413,
        )


def save_bundle_upload(upload, workdir, budget):
    path = os.path.join(workdir, "input.bundle")
    multipart_bytes = 0
    for _, part in request.files.items(multi=True):
        position = part.stream.tell()
        part.stream.seek(0, os.SEEK_END)
        multipart_bytes += part.stream.tell()
        part.stream.seek(position)
    # 也计入重复字段或额外文件的框架暂存，不能只计算选中的 Bundle。
    budget.set_disk_size("multipart", multipart_bytes)
    size = 0
    with open(path, "wb") as output:
        while True:
            chunk = upload.stream.read(64 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BUNDLE_SIZE:
                raise export_limits.exceeded("Bundle 上传超过 140 MiB")
            budget.set_disk_size("upload", size)
            output.write(chunk)
    if not size:
        raise ClientFacingError("Bundle 文件为空，请重新上传。")
    with open(path, "rb") as source:
        if source.read(4) == b"PK\x03\x04":
            raise ClientFacingError("请上传 Bundle 文件，ZIP 请先解压后再选择 Bundle。")
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
    def cleanup_after_download(response):
        def cleanup():
            try:
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                elif os.path.exists(path):
                    os.remove(path)
                gc.collect()
            except OSError:
                pass
        # 保持流式下载，在文件流关闭后清理，兼容 Windows 的打开文件限制。
        response.direct_passthrough = False
        response.call_on_close(cleanup)
        return response


def read_text_from_zip(patch, path):
    raw_bytes = patch.read(path)

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
    def from_csv(csv_text, original_tree=None):
        result = {}
        original_tree = original_tree if isinstance(original_tree, dict) else {}
        reader = csv.reader(io.StringIO(csv_text))
        row_number = 0
        while True:
            try:
                row = next(reader)
            except StopIteration:
                break
            except csv.Error as exc:
                if "field larger" in str(exc):
                    raise patch_limits.limit_error("CSV 单字段超过解析上限") from exc
                raise ClientFacingError(f"CSV 格式无法解析：{exc}") from exc
            row_number += 1
            if row_number > patch_limits.CSV_MAX_ROWS:
                raise patch_limits.limit_error(f"CSV 行数超过 {patch_limits.CSV_MAX_ROWS} 行")
            if len(row) > patch_limits.CSV_MAX_COLUMNS:
                raise patch_limits.limit_error(f"CSV 列数超过 {patch_limits.CSV_MAX_COLUMNS} 列")
            if any(len(value) > patch_limits.CSV_MAX_FIELD_CHARS for value in row):
                raise patch_limits.limit_error("CSV 单字段超过 128 KiB 字符上限")
            if len(row) >= 2 and row[0].strip():
                key, value = row[0].strip(), row[1]
                if value.startswith(("{", "[")):
                    try:
                        value = load_patch_json(value, f"CSV 第 {row_number} 行")
                    except ClientFacingError:
                        raise
                    except ValueError:
                        pass
                elif type(original_tree.get(key)) in (int, float, bool):
                    # CSV 无类型信息；只按原 typetree 恢复标量，字符串不做猜测转换。
                    expected = type(original_tree[key])
                    try:
                        if expected is bool and value.strip().lower() in {"true", "false"}:
                            scalar = value.strip().lower() == "true"
                        else:
                            scalar = json.loads(value)
                    except ValueError as exc:
                        raise ClientFacingError(f"CSV 字段 [{key}] 需要合法的数字或 true/false。") from exc
                    if type(scalar) is not expected:
                        if expected is float and type(scalar) is int:
                            scalar = float(scalar)
                        else:
                            raise ClientFacingError(f"CSV 字段 [{key}] 类型与原对象不一致。")
                    value = scalar
                result[key] = value
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
    - manual：保留 indent=4 可读格式，并按原文本换行风格输出
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

    try:
        parsed = load_patch_json(text, source_label)
    except ClientFacingError:
        raise
    except Exception as exc:
        raise ClientFacingError(format_json_parse_error(exc, text, source_label)) from exc

    if not isinstance(parsed, dict):
        raise ClientFacingError(
            f"{source_label} 根节点必须是对象 {{...}}（Unity typetree），"
            f"当前是 {type(parsed).__name__}。"
            "数组/字符串/数字无法 save_typetree，请使用本站解包导出的 JSON。"
        )

    return parsed


def collect_typetree_shape_issues(tree, obj_type_name=None):
    """仅保留正式写入需要的阻断性检查，不再生成预检警告。"""
    if not isinstance(tree, dict) or not tree:
        return ["JSON 必须是非空对象，无法写回空 typetree"]
    hard = []

    def walk(node, path=""):
        if isinstance(node, dict):
            if is_pptr_like(node):
                return
            for key, value in node.items():
                field = f"{path}.{key}" if path else key
                if key == "m_Script" and obj_type_name == "MonoBehaviour":
                    if isinstance(value, str) or (isinstance(value, dict) and not is_pptr_like(value)):
                        hard.append(f"{field} 在 MonoBehaviour 中必须是 PPtr 引用 {{m_FileID, m_PathID}}")
                if isinstance(value, (dict, list)):
                    walk(value, field)
        elif isinstance(node, list):
            for index, item in enumerate(node):
                if isinstance(item, (dict, list)):
                    walk(item, f"{path}[{index}]")

    walk(tree)
    return hard


def prepare_typetree_for_inject(new_tree, process_mode="auto", obj_type_name=None, source_label="JSON"):
    """
    collapse 嵌入 JSON + 还原误导出的 PPtr 字符串，并做结构校验。
    返回可 save_typetree 的 dict。

    阻断性检查只看「restore + collapse 之后」的最终树，避免把仍可自动修复的
    PPtr 字符串误判为 hard error。
    """
    if not isinstance(new_tree, dict):
        raise ClientFacingError(f"{source_label} 根节点必须是对象。")
    check_json_tree(new_tree, source_label)

    # 先 restore，再 collapse 嵌入 JSON，最后再 restore 一轮（嵌套历史坏导出）
    tree = restore_pptr_fields(new_tree)
    collapsed = transform_json_tree(tree, mode="collapse", process_strategy=process_mode)
    collapsed = restore_pptr_fields(collapsed)

    hard = collect_typetree_shape_issues(collapsed, obj_type_name=obj_type_name)
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
    except MemoryError:
        raise
    except Exception as save_err:
        collapsed = restore_pptr_fields(collapsed)
        try:
            obj.save_typetree(collapsed)
            return
        except MemoryError:
            raise
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
                    # TextAsset 正文：manual 模式保留 pretty+原换行；auto 紧凑（语义等价）
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
                    parsed = load_patch_json(clean_json_string(v), f"字段 {k}")
                except ClientFacingError:
                    raise
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


# ==================== ZIP 补丁匹配 ====================

def build_zip_patch_maps(patch):
    zip_file_map = {}
    fallback_map = {}
    index_data = {}
    index_path = None

    for info in patch.members:
        name = info.filename
        if is_ignored_zip_entry(name):
            continue

        normalized_name = name.replace('\\', '/')
        file_name_only = normalized_name.split('/')[-1]

        if not file_name_only.lower().endswith(('.json', '.json5', '.csv')):
            raise ClientFacingError(f"补丁 [{file_name_only}] 格式不支持；在线回填只支持 JSON 或 CSV。")
        zip_file_map[file_name_only] = name

        match = re.search(r'_(\d+)\.(json5?|csv)$', file_name_only, re.IGNORECASE)
        if match:
            fallback_map[match.group(1)] = name

        if file_name_only == '_index.json':
            index_path = name

    if index_path is not None:
        raw_index = read_text_from_zip(patch, index_path)
        try:
            index_data = load_patch_json(clean_json_string(raw_index), "_index.json")
        except ClientFacingError:
            raise
        except Exception as exc:
            raise ClientFacingError(format_json_parse_error(exc, raw_index, "_index.json")) from exc

        if not isinstance(index_data, dict):
            raise ClientFacingError(
                "_index.json 根节点必须是对象：{ \"path_id\": \"相对路径/文件名.json\", ... }"
            )
        bad_keys = [k for k, v in index_data.items() if not isinstance(v, str) or not v.strip()]
        if bad_keys:
            sample = ", ".join(str(k) for k in bad_keys[:5])
            raise ClientFacingError(
                f"_index.json 中有 {len(bad_keys)} 个无效条目（值必须是非空路径字符串），例如键：{sample}"
            )

    return zip_file_map, fallback_map, index_data


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
        expected_filename = actual_zip_path.replace('\\', '/').split('/')[-1]
        match_source = "filename_path_id"

    return actual_zip_path, expected_filename, match_source


# ==================== 解包策略 ====================


def get_unpack_policy():
    target_format = request.form.get('format', 'json')
    process_mode = request.form.get('mode', 'auto')
    if any(name in request.form for name in ('preset', 'types', 'include_images', 'include_index')):
        raise ClientFacingError("导出选项已精简，请使用 JSON 或 CSV 导出。")
    if target_format not in {'json', 'csv'}:
        raise ClientFacingError("导出格式只支持 JSON 或 CSV。")
    if process_mode not in {'auto', 'manual'}:
        raise ClientFacingError("文本处理方式无效。")
    return {"target_format": target_format, "process_mode": process_mode}


def prepare_export_tree(tree, policy, budget):
    """仅在正式导出时展开内嵌 JSON；使用有预算的迭代遍历。"""
    nodes = 0

    def children(mapping):
        for key, value in mapping.items():
            yield key
            if (key in STRING_EMBEDDED_JSON_KEYS and isinstance(value, str)
                    and looks_like_json_text(value)):
                if len(value) > export_limits.TREE_MAX_STRING_CHARS:
                    raise export_limits.exceeded("内嵌 JSON 字符串过长")
                text = clean_json_string(value) if policy["process_mode"] == "auto" else value
                try:
                    patch_limits.check_json_text(text, "Bundle 内嵌 JSON", max_bytes=export_limits.TEXT_MAX_BYTES,
                                                 max_depth=export_limits.TREE_MAX_DEPTH, max_nodes=export_limits.TREE_MAX_NODES)
                except ClientFacingError as exc:
                    raise export_limits.exceeded("Bundle 内嵌 JSON 结构过于复杂") from exc
                try:
                    value = json.loads(text)
                except json.JSONDecodeError:
                    if len(text.encode("utf-8")) > export_limits.JSON5_MAX_BYTES:
                        raise export_limits.exceeded("非标准内嵌 JSON 超过 JSON5 解析预算")
                    try:
                        value = json5.loads(text)
                    except RecursionError as exc:
                        raise export_limits.exceeded("Bundle 内嵌 JSON 结构过于复杂") from exc
                    except ValueError:
                        pass
                mapping[key] = value
            yield value

    stack = [(iter((tree,)), 1)]
    while stack:
        values, depth = stack[-1]
        try:
            value = next(values)
        except StopIteration:
            stack.pop()
            continue
        nodes += 1
        budget.tree_nodes += 1
        if (nodes > export_limits.TREE_MAX_NODES or budget.tree_nodes > export_limits.TREE_TOTAL_NODES
                or depth > export_limits.TREE_MAX_DEPTH):
            raise export_limits.exceeded("Bundle 文本结构过于复杂")
        if isinstance(value, str):
            if len(value) > export_limits.TREE_MAX_STRING_CHARS:
                raise export_limits.exceeded("Bundle 文本字符串过长")
            try:
                value.encode("utf-8")
            except UnicodeError as exc:
                raise ClientFacingError("Bundle 文本包含无效 UTF-8 字符。") from exc
        elif isinstance(value, dict):
            stack.append((children(value), depth + 1))
        elif isinstance(value, list):
            stack.append((iter(value), depth + 1))
        elif value is not None and not isinstance(value, (int, float, bool)):
            raise ValueError("对象字段不支持 JSON 导出")
    return tree


def export_typetree_object(obj, zf, index_data, policy, budget):
    budget.reserve_source(obj)
    tree = obj.read_typetree()
    if not tree:
        return False

    tree = prepare_export_tree(tree, policy, budget)
    name = safe_name(export_limits.check_name(tree.get("m_Name", f"Object_{obj.path_id}"))) if isinstance(tree, dict) else f"Object_{obj.path_id}"
    base_name = f"{obj.type.name}/{name}_{obj.path_id}"

    if policy["target_format"] == 'csv':
        budget.start_file()
        with zf.open(f"{base_name}.csv", "w") as output:
            sink = export_limits.MemberWriter(output, budget)
            sink.write("\ufeff")
            writer = csv.writer(sink, lineterminator='\n')
            if isinstance(tree, dict):
                for key, value in tree.items():
                    if isinstance(value, (dict, list)):
                        parts, size = [], 0
                        for chunk in export_limits.json_chunks(value):
                            size += len(chunk.encode("utf-8"))
                            if size > export_limits.TEXT_MAX_BYTES:
                                raise export_limits.exceeded("CSV 字段内容过大")
                            parts.append(chunk)
                        value = "".join(parts)
                    writer.writerow([key, value])
        index_data[str(obj.path_id)] = f"{base_name}.csv"
    else:
        export_limits.write_json_member(zf, f"{base_name}.json", tree, budget)
        index_data[str(obj.path_id)] = f"{base_name}.json"

    return True


# ==================== 页面 ====================

@unity_bp.route('/unity')
def index():
    return render_template('tab_unity.html', current_tab='unity')


# ==================== 解包导出 ====================

@unity_bp.route('/unpack', methods=['POST'])
def unpack():
    lock_response = acquire_unity_lock(json_response=False)
    if lock_response:
        return lock_response

    workdir = None
    download_ready = False
    try:
        workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
        cleanup_old_temp()
        reject_if_too_large(MAX_BUNDLE_SIZE, "Bundle 文件")
        file = request.files.get('bundle')

        if not file:
            return _client_error("请选择文件。", 400)

        policy = get_unpack_policy()
        export_limits.check_name(file.filename)
        budget = export_limits.ExportBudget()
        bundle_path = save_bundle_upload(file, workdir, budget)
        output_zip_path = os.path.join(workdir, "output.zip")

        env = UnityPy.load(bundle_path)
        index_data = {}
        exported_count = 0
        skipped_count = 0
        failed_count = 0

        with open(output_zip_path, "w+b") as output, zipfile.ZipFile(
                export_limits.BoundedOutput(output, budget, "zip", export_limits.ZIP_MAX_BYTES, "输出 ZIP"),
                'w', zipfile.ZIP_DEFLATED) as zf:
            for obj in export_limits.iter_objects(env):
                if obj.type.name not in TEXT_OBJECT_TYPES:
                    skipped_count += 1
                    continue

                try:
                    if export_typetree_object(obj, zf, index_data, policy, budget):
                        exported_count += 1
                    else:
                        skipped_count += 1

                except (ClientFacingError, MemoryError, RecursionError, OSError):
                    raise
                except Exception:
                    failed_count += 1

            export_limits.write_json_member(zf, "_index.json", index_data, budget)

            export_limits.write_json_member(zf, "_export_summary.json", {
                "format": policy["target_format"],
                "selected_types": sorted(TEXT_OBJECT_TYPES),
                "exported_count": exported_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count
            }, budget)

        if exported_count == 0:
            return _client_error("没有可导出的 MonoBehaviour 或 TextAsset 文本对象。", 400)

        response = send_file(
            output_zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"Unpacked_{safe_name(file.filename)}.zip"
        )
        register_cleanup(workdir)
        download_ready = True
        return response

    except ClientFacingError as e:
        return _client_error(str(e), getattr(e, "status", 400))
    except RequestEntityTooLarge:
        return _client_error("上传内容超过在线版限制。", 413)
    except RecursionError:
        return _client_error("Bundle 结构过于复杂，请使用本地工具。", 413)
    except Exception as e:
        return _client_error(f"解包失败: {e}", 500)
    finally:
        if workdir and not download_ready:
            shutil.rmtree(workdir, ignore_errors=True)
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
        except MemoryError:
            raise
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

    workdir = None
    download_ready = False
    try:
        workdir = tempfile.mkdtemp(prefix=TEMP_PREFIX)
        cleanup_old_temp()
        reject_if_too_large(MAX_BUNDLE_SIZE + MAX_PATCH_ZIP_SIZE, "上传内容")
        orig_file = request.files.get('original_bundle')
        mod_zip = request.files.get('modified_zip')
        process_mode = request.form.get('mode', 'auto')
        if not orig_file or not mod_zip:
            raise ClientFacingError("缺少文件！请同时上传原始 Bundle 与修改后的 ZIP。")
        if not (orig_file.filename or "").strip():
            raise ClientFacingError("原始 Bundle 文件名为空，请重新选择文件。")
        if not (mod_zip.filename or "").strip():
            raise ClientFacingError("修改后的 ZIP 文件名为空，请重新选择文件。")

        # 固定内部文件名，避免两份上传重名；原始名称仅用于下载名称。
        orig_path = os.path.join(workdir, "original.bundle")
        zip_path = os.path.join(workdir, "patch.zip")
        output_bundle_path = os.path.join(workdir, "output.bundle")
        orig_file.save(orig_path)
        mod_zip.save(zip_path)
        for path, limit, label in (
            (orig_path, MAX_BUNDLE_SIZE, "原始 Bundle"),
            (zip_path, MAX_PATCH_ZIP_SIZE, "修改后的 ZIP"),
        ):
            size = os.path.getsize(path)
            if size == 0:
                raise ClientFacingError(f"{label} 文件大小为 0，请重新上传完整文件。")
            if size > limit:
                raise patch_limits.limit_error(f"{label} 超过 {limit // patch_limits.MIB} MiB 上传上限")
        with open(orig_path, 'rb') as fp:
            if fp.read(4) == b'PK\x03\x04':
                # UnityPy 会自动识别 ZIP；原始文件槽不能绕过补丁 ZIP 的预算。
                raise ClientFacingError("原始文件是 ZIP，请先取出原始 Bundle；ZIP 只能作为修改后的补丁上传。")

        # ZIP 元数据和索引预算先于 UnityPy 加载；不做 testzip 或全包正文扫描。
        with open_patch_zip(zip_path) as patch:
            zip_file_map, fallback_map, index_data = build_zip_patch_maps(patch)
            try:
                env = UnityPy.load(orig_path)
            except MemoryError:
                raise
            except Exception as exc:
                raise ClientFacingError(
                    f"无法解析原始 Bundle，请确认文件完整且为 Unity AssetBundle。详情：{exc}"
                ) from exc
            modified_files_count = 0
            for obj in env.objects:
                actual_zip_path, expected_filename, _ = find_patch_for_object(
                    obj, zip_file_map, fallback_map, index_data,
                )
                if not actual_zip_path:
                    continue
                try:
                    lower_name = expected_filename.lower()
                    if obj.type.name not in TEXT_OBJECT_TYPES:
                        raise ClientFacingError(f"对象类型 {obj.type.name} 不支持文本回填，只支持 MonoBehaviour / TextAsset。")
                    if lower_name.endswith(('.json', '.json5')):
                        new_tree = parse_patch_json(
                            read_text_from_zip(patch, actual_zip_path),
                            process_mode=process_mode, source_label=expected_filename,
                        )
                        inject_typetree_to_object(
                            obj, new_tree, process_mode=process_mode, source_label=expected_filename,
                        )
                    elif lower_name.endswith('.csv'):
                        csv_text = read_text_from_zip(patch, actual_zip_path)
                        if not csv_text.strip():
                            raise ClientFacingError(f"{expected_filename} CSV 文件为空")
                        new_tree = FormatManager.from_csv(csv_text, original_tree=obj.read_typetree())
                        if not new_tree:
                            raise ClientFacingError(
                                f"{expected_filename} CSV 未能解析为对象字段表（需要至少两列：字段名,值）"
                            )
                        inject_typetree_to_object(
                            obj, new_tree, process_mode=process_mode, source_label=expected_filename,
                        )
                    else:
                        raise ClientFacingError("在线回填只支持 JSON 或 CSV 补丁。")
                    modified_files_count += 1
                except ClientFacingError as exc:
                    msg = str(exc)
                    if expected_filename not in msg:
                        msg = f"文件 [{expected_filename}]：{msg}"
                    raise ClientFacingError(msg, status=exc.status) from exc
                except MemoryError:
                    raise
                except Exception as exc:
                    raise ClientFacingError(f"文件 [{expected_filename}] 注入失败：{exc}") from exc
            if modified_files_count == 0:
                raise ClientFacingError(
                    "没有检测到任何可注入的补丁文件。请检查 ZIP 是否来自当前 Bundle 的导出结果，"
                    "是否保留 _index.json 或文件名中的 path_id，以及原始 Bundle 是否选错版本。"
                )

        # UnityPy 仍会生成完整输出 bytes，落盘并不能限制库内部的峰值内存。
        saved_bytes = _save_bundle_bytes(env)
        with open(output_bundle_path, 'wb') as fp:
            fp.write(saved_bytes)
        del saved_bytes
        gc.collect()
        response = send_file(
            output_bundle_path, mimetype='application/octet-stream', as_attachment=True,
            download_name=f"modded_{safe_name(orig_file.filename)}",
        )
        register_cleanup(workdir)
        download_ready = True
        return response
    except ClientFacingError as exc:
        return _client_error(str(exc), exc.status)
    except zipfile.BadZipFile:
        return _client_error("修改包不是有效的 ZIP，或匹配成员已损坏，请重新打包后再试。", 400)
    except RequestEntityTooLarge:
        return _client_error("上传内容超过服务器的请求大小上限，请缩小文件后再试。", 413)
    except MemoryError:
        gc.collect()
        return _client_error("服务器内存不足，回填中止。请缩小补丁或使用本地工具。", 507)
    except Exception as exc:
        import traceback
        print(f"[repack] FAILED: {exc}")
        traceback.print_exc()
        return _client_error(f"打包未能完成：{exc}。请保留原文件备份，并确认补丁格式和 Bundle 版本。", 500)
    finally:
        if workdir and not download_ready:
            shutil.rmtree(workdir, ignore_errors=True)
        release_unity_lock()
