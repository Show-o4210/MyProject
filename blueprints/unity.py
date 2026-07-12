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


def reject_if_too_large(max_size, label="文件"):
    content_length = request.content_length
    if content_length and content_length > max_size:
        mb = max_size // 1024 // 1024
        raise ValueError(f"{label}过大。在线版当前限制约 {mb}MB；更大的 Bundle 建议使用本地版或仅上传补丁包。")


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
        writer = csv.writer(output)

        if isinstance(data_dict, dict):
            for key, value in data_dict.items():
                val_str = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                writer.writerow([key, val_str])

                for _ in range(3):
                    writer.writerow([])

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
# 切勿包含 m_Script：在 Unity 里它是 PPtr（{m_FileID, m_PathID}），
# collapse 成字符串会导致 save_typetree 报 'str' object has no attribute 'm_FileID'。
STRING_EMBEDDED_JSON_KEYS = {
    "m_Data",
    "m_RawData",
    "m_ScriptText",
    "jsonData",
    "JsonData",
    "dataJson",
    "rawJson",
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
    return (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]"))


def parse_embedded_json(text, process_strategy="auto"):
    cleaned = clean_json_string(text) if process_strategy == "auto" else text
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        try:
            return json5.loads(cleaned)
        except Exception:
            return text


def transform_json_tree(tree, mode="expand", process_strategy="auto"):
    """
    expand：把「字符串形式的嵌入 JSON」解析成对象，便于编辑。
    collapse：把上述字段重新压回字符串，再 save_typetree。

    重要：
    - 不处理 m_Script / 任意 PPtr 形态字段
    - 非 STRING_EMBEDDED_JSON_KEYS 的 dict/list 只递归，不 stringify
    """
    if isinstance(tree, dict):
        for k, v in list(tree.items()):
            if is_pptr_like(v):
                continue

            if k in STRING_EMBEDDED_JSON_KEYS:
                if mode == "expand" and isinstance(v, str) and looks_like_json_text(v):
                    parsed = parse_embedded_json(v, process_strategy)
                    tree[k] = parsed
                    if isinstance(parsed, (dict, list)):
                        transform_json_tree(parsed, mode, process_strategy)

                elif mode == "collapse" and isinstance(v, (dict, list)):
                    # PPtr 误入 m_Data 时也不折叠
                    if is_pptr_like(v):
                        continue
                    transform_json_tree(v, mode, process_strategy)
                    separators = (",", ":") if process_strategy == "auto" else None
                    tree[k] = json.dumps(v, separators=separators, ensure_ascii=False)

                elif isinstance(v, (dict, list)):
                    transform_json_tree(v, mode, process_strategy)

            elif isinstance(v, (dict, list)):
                transform_json_tree(v, mode, process_strategy)

    elif isinstance(tree, list):
        for item in tree:
            if isinstance(item, (dict, list)):
                transform_json_tree(item, mode, process_strategy)

    return tree


def restore_pptr_fields(tree):
    """
    兼容旧版错误导出：曾把 m_Script 等 PPtr collapse 成 JSON 字符串。
    回填前把可识别的 PPtr 字符串还原为 dict，避免 save_typetree 失败。
    """
    pptr_keys = {
        "m_Script",
        "m_GameObject",
        "m_Father",
        "m_Controller",
        "m_Mesh",
        "m_Material",
        "m_Font",
        "m_Texture",
        "m_Sprite",
    }

    if isinstance(tree, dict):
        for k, v in list(tree.items()):
            if isinstance(v, str) and (k in pptr_keys or k.startswith("m_")) and looks_like_json_text(v):
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
                index_data = json.loads(read_text_from_zip(zf, name))
            except Exception as e:
                raise Exception(f"解析 _index.json 失败: {e}")

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
                    cleaned_str = clean_json_string(raw_json_str) if process_mode == 'auto' else raw_json_str
                    parsed = json.loads(cleaned_str)

                    if not isinstance(parsed, (dict, list)):
                        item["status"] = "warning"
                        item["level"] = "warning"
                        item["message"] = "JSON 不是对象或数组，可能无法正确 save_typetree"
                    else:
                        item["message"] = "JSON 格式有效，可回填"

            elif lower_name.endswith('.csv'):
                if validate_level == 'full':
                    csv_text = read_text_from_zip(zf, actual_zip_path)
                    parsed = FormatManager.from_csv(csv_text)

                    if not parsed:
                        item["status"] = "warning"
                        item["level"] = "warning"
                        item["message"] = "CSV 未解析出有效字段"
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

        except Exception as e:
            item["status"] = "error"
            item["level"] = "danger"
            item["message"] = str(e)

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
        env = UnityPy.load(bundle_path)
        report = inspect_env_light(env) if inspect_depth == 'fast' else inspect_env(env)

        return jsonify({
            "success": True,
            "filename": file.filename,
            "report": report
        })

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 413
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
            return render_template('error.html', msg="没有导出任何对象。请切换为高级自定义，或选择更多对象类型。"), 400

        register_cleanup(workdir)
        return send_file(
            output_zip_path,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"Unpacked_{safe_name(file.filename)}.zip"
        )

    except ValueError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return render_template('error.html', msg=str(e)), 413
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return render_template('error.html', msg=f"解包失败: {e}"), 500
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

        orig_path = save_upload_to_workdir(orig_file, workdir, "original_bundle")
        zip_path = save_upload_to_workdir(mod_zip, workdir, "modified.zip")

        env = UnityPy.load(orig_path)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            report = validate_patch_against_bundle(
                env,
                zf,
                process_mode=process_mode,
                validate_level=validate_level,
                repack_mode=repack_mode
            )

        return jsonify({"success": True, "report": report})

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 413
    except Exception as e:
        return jsonify({"success": False, "error": f"预检失败：{e}"}), 500
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        gc.collect()
        release_unity_lock()


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
            return render_template('error.html', msg="缺少文件！"), 400

        orig_path = save_upload_to_workdir(orig_file, workdir, "original_bundle")
        zip_path = save_upload_to_workdir(mod_zip, workdir, "modified.zip")
        output_bundle_path = os.path.join(workdir, f"modded_{safe_name(orig_file.filename)}")

        env = UnityPy.load(orig_path)

        with zipfile.ZipFile(zip_path, 'r') as zf:
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
                    return render_template(
                        'error.html',
                        msg=f"预检未通过，已中止打包。错误数：{validate_report['summary']['errors']}。请先回到页面执行预检查看详情。"
                    ), 400

            zip_file_map, fallback_map, index_data, _ = build_zip_patch_maps(zf)
            modified_files_count = 0

            for obj in env.objects:
                path_id_str = str(obj.path_id)
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
                                pil_img = Image.open(img_fp).convert('RGBA')
                                data.image = pil_img
                                data.save()
                            modified_files_count += 1
                        else:
                            raise Exception("试图将 PNG 回填给非贴图类型对象")

                    elif lower_name.endswith('.json'):
                        raw_json_str = read_text_from_zip(zf, actual_zip_path)
                        cleaned_str = clean_json_string(raw_json_str) if process_mode == 'auto' else raw_json_str
                        try:
                            new_tree = json.loads(cleaned_str)
                        except json.JSONDecodeError:
                            new_tree = json5.loads(cleaned_str)

                        if not isinstance(new_tree, dict):
                            raise Exception("JSON 根节点必须是对象（typetree dict），不能是数组或原始值")

                        # 将可编辑的嵌入 JSON 压回字符串；PPtr（含 m_Script）保持 dict
                        collapsed_tree = transform_json_tree(
                            new_tree, mode='collapse', process_strategy=process_mode
                        )
                        # 防御：若旧版导出/手改把 m_Script 弄成了字符串，尝试解析回来
                        collapsed_tree = restore_pptr_fields(collapsed_tree)
                        obj.save_typetree(collapsed_tree)
                        modified_files_count += 1

                    elif lower_name.endswith('.csv'):
                        csv_text = read_text_from_zip(zf, actual_zip_path)
                        new_tree = FormatManager.from_csv(csv_text)

                        if not isinstance(new_tree, dict):
                            raise Exception("CSV 未能解析为对象字段表")

                        collapsed_tree = transform_json_tree(
                            new_tree, mode='collapse', process_strategy=process_mode
                        )
                        collapsed_tree = restore_pptr_fields(collapsed_tree)
                        obj.save_typetree(collapsed_tree)
                        modified_files_count += 1

                    else:
                        obj.set_raw_data(zf.read(actual_zip_path))
                        modified_files_count += 1

                except Exception as e:
                    raise Exception(f"文件 [{expected_filename}] 注入失败：{e}") from e

            if modified_files_count == 0:
                raise Exception(
                    "没有检测到任何被修改的内容被注入，请检查文件名、_index.json 或 Bundle 是否匹配"
                )

        # UnityPy 的 save 本身会产生完整输出，无法完全避免峰值；但落盘返回可以减少后续复制。
        try:
            saved_bytes = env.file.save(packer="lz4")
        except Exception:
            # 个别资源对 lz4 打包敏感时回退默认 packer
            saved_bytes = env.file.save()

        with open(output_bundle_path, 'wb') as fp:
            fp.write(saved_bytes)

        register_cleanup(workdir)
        return send_file(
            output_bundle_path,
            mimetype='application/octet-stream',
            as_attachment=True,
            download_name=f"modded_{safe_name(orig_file.filename)}"
        )

    except ValueError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return render_template('error.html', msg=str(e)), 413
    except Exception as e:
        shutil.rmtree(workdir, ignore_errors=True)
        return render_template('error.html', msg=f"打包异常中止！原因：{e}"), 500
    finally:
        release_unity_lock()
