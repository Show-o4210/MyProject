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

# Render 免费套餐内存较小，Unity 任务统一串行执行，避免并发解包直接打爆内存。
UNITY_TASK_LOCK = threading.Lock()

MAX_BUNDLE_SIZE = 140 * 1024 * 1024      # 140MB，在线版硬限制
MAX_PATCH_ZIP_SIZE = 90 * 1024 * 1024    # 90MB，回填补丁包硬限制
TEMP_PREFIX = "unity_tool_"

LIGHT_EDITABLE_TYPES = {"MonoBehaviour", "TextAsset", "Texture2D", "Sprite", "GameObject", "Material"}
JSON_LIKE_TYPES = {"MonoBehaviour", "TextAsset", "GameObject", "Material", "AnimationClip", "AnimatorController"}
IMAGE_TYPES = {"Texture2D", "Sprite"}
DEFAULT_RECOMMENDED_TYPES = ["MonoBehaviour", "TextAsset"]
DEFAULT_PATCH_TYPES = ["MonoBehaviour", "TextAsset"]
DEFAULT_IMAGE_TYPES = ["Texture2D", "Sprite"]


# ==================== 基础工具 ====================

def acquire_unity_lock(json_response=False):
    if UNITY_TASK_LOCK.acquire(blocking=False):
        return None

    msg = "当前已有 Unity 资源任务正在处理，请稍后再试。免费服务器内存有限，暂不支持并发解包/回填。"
    if json_response:
        return jsonify({"success": False, "error": msg}), 429
    return render_template('error.html', msg=msg), 429


def release_unity_lock():
    try:
        UNITY_TASK_LOCK.release()
    except RuntimeError:
        pass


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


def transform_json_tree(tree, mode='expand', process_strategy='auto'):
    target_keys = {"m_Script", "m_Data", "m_RawData"}

    if isinstance(tree, dict):
        for k, v in tree.items():
            if k in target_keys:
                if mode == 'expand' and isinstance(v, str):
                    cleaned_v = clean_json_string(v) if process_strategy == 'auto' else v

                    if (
                        (cleaned_v.startswith('{') and cleaned_v.endswith('}'))
                        or (cleaned_v.startswith('[') and cleaned_v.endswith(']'))
                    ):
                        try:
                            tree[k] = json.loads(cleaned_v)
                            transform_json_tree(tree[k], mode, process_strategy)
                        except json.JSONDecodeError:
                            try:
                                tree[k] = json5.loads(cleaned_v)
                                transform_json_tree(tree[k], mode, process_strategy)
                            except Exception:
                                tree[k] = cleaned_v

                elif mode == 'collapse' and isinstance(v, (dict, list)):
                    transform_json_tree(v, mode, process_strategy)
                    separators = (',', ':') if process_strategy == 'auto' else None
                    tree[k] = json.dumps(v, separators=separators, ensure_ascii=False)
            else:
                if isinstance(v, (dict, list)):
                    transform_json_tree(v, mode, process_strategy)

    elif isinstance(tree, list):
        for item in tree:
            if isinstance(item, (dict, list)):
                transform_json_tree(item, mode, process_strategy)

    return tree


# ==================== Bundle 分析 ====================

def guess_export_modes(type_name):
    if type_name in IMAGE_TYPES:
        return ["png", "raw"]
    if type_name in JSON_LIKE_TYPES or type_name in LIGHT_EDITABLE_TYPES:
        return ["json", "csv", "raw"]
    return ["raw"]


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
            item["export_modes"] = ["png", "raw"]

        else:
            try:
                tree = obj.read_typetree()
                if tree:
                    item["editable"] = True
                    item["export_modes"] = ["json", "csv", "raw"]
                else:
                    item["export_modes"] = ["raw"]
            except Exception:
                item["export_modes"] = ["raw"]

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
    fallback_raw = parse_bool_form('fallback_raw', False)
    include_index = parse_bool_form('include_index', True)

    if preset == 'recommended':
        selected_types = DEFAULT_RECOMMENDED_TYPES
        target_format = 'json'
        include_images = False
        fallback_raw = False
        include_index = True
    elif preset == 'patch':
        selected_types = DEFAULT_PATCH_TYPES
        target_format = 'json'
        include_images = False
        fallback_raw = False
        include_index = True
    elif preset == 'images':
        selected_types = DEFAULT_IMAGE_TYPES
        target_format = 'json'
        include_images = True
        fallback_raw = False
        include_index = True
    elif preset == 'advanced':
        if not selected_types:
            selected_types = DEFAULT_RECOMMENDED_TYPES
    elif preset == 'raw':
        target_format = 'raw'
        fallback_raw = True
        include_index = True
        if not selected_types:
            selected_types = ['__all__']

    return {
        "preset": preset,
        "target_format": target_format,
        "process_mode": process_mode,
        "selected_types": selected_types,
        "include_images": include_images,
        "fallback_raw": fallback_raw,
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


def export_raw_object(obj, zf, index_data):
    raw_data = obj.get_raw_data()
    file_name = f"Raw/{obj.type.name}_{obj.path_id}.dat"
    zf.writestr(file_name, raw_data)
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
                        elif policy["target_format"] == 'raw':
                            export_raw_object(obj, zf, index_data)
                            exported_count += 1
                        else:
                            skipped_count += 1
                        continue

                    if policy["target_format"] == 'raw':
                        export_raw_object(obj, zf, index_data)
                        exported_count += 1
                        continue

                    if export_typetree_object(obj, zf, index_data, policy):
                        exported_count += 1
                    elif policy["fallback_raw"]:
                        export_raw_object(obj, zf, index_data)
                        exported_count += 1
                    else:
                        skipped_count += 1

                except Exception:
                    failed_count += 1
                    if policy["fallback_raw"]:
                        try:
                            export_raw_object(obj, zf, index_data)
                            exported_count += 1
                        except Exception:
                            pass

            if policy["include_index"]:
                zf.writestr("_index.json", json.dumps(index_data, indent=4, ensure_ascii=False))

            zf.writestr("_export_summary.json", json.dumps({
                "preset": policy["preset"],
                "format": policy["target_format"],
                "selected_types": policy["selected_types"],
                "include_images": policy["include_images"],
                "fallback_raw": policy["fallback_raw"],
                "exported_count": exported_count,
                "skipped_count": skipped_count,
                "failed_count": failed_count
            }, indent=4, ensure_ascii=False))

        if exported_count == 0:
            shutil.rmtree(workdir, ignore_errors=True)
            return render_template('error.html', msg="没有导出任何对象。请切换为高级自定义，选择更多对象类型，或开启 RAW 兜底。"), 400

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
            # 正式合成前使用完整预检，避免快速预检漏掉损坏 JSON / PNG。
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
                    msg=f"预检未通过，已中止打包。错误数：{validate_report['summary']['errors']}。请先回到页面执行完整预检查看详情。"
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
                        new_tree = json.loads(cleaned_str)

                        collapsed_tree = transform_json_tree(new_tree, mode='collapse', process_strategy=process_mode)
                        obj.save_typetree(collapsed_tree)
                        modified_files_count += 1

                    elif lower_name.endswith('.csv'):
                        csv_text = read_text_from_zip(zf, actual_zip_path)
                        new_tree = FormatManager.from_csv(csv_text)

                        collapsed_tree = transform_json_tree(new_tree, mode='collapse', process_strategy=process_mode)
                        obj.save_typetree(collapsed_tree)
                        modified_files_count += 1

                    else:
                        obj.set_raw_data(zf.read(actual_zip_path))
                        modified_files_count += 1

                except Exception as e:
                    raise Exception(f"文件 [{expected_filename}] 注入失败：{e}")

            if modified_files_count == 0:
                raise Exception("没有检测到任何被修改的内容被注入，请检查文件名、_index.json 或 Bundle 是否匹配")

        # UnityPy 的 save 本身会产生完整输出，无法完全避免峰值；但落盘返回可以减少后续复制。
        with open(output_bundle_path, 'wb') as fp:
            fp.write(env.file.save(packer="lz4"))

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
