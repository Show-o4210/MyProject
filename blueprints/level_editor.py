# blueprints/level_editor.py
import os
import tempfile
import shutil
import gc
from flask import Blueprint, render_template, jsonify, send_file
from logic_level_editor import LevelEditorLogic
from extensions import acquire_unity_lock, release_unity_lock
from utils.unity_jobs import run_unity_job
from utils.patch_limits import ClientFacingError
from utils.json_requests import (
    JsonInputError, json_error_response, read_json_object,
    validate_level_id, serialize_level_config,
)

# 假定把桌面端的常量直接放在这里，或者从独立的 utils/constants.py 导入
from data.constants import PLANT_HEROES, ZOMBIE_HEROES, SCENES, ALL_HEROES

level_editor_bp = Blueprint('level_editor', __name__)
logic = LevelEditorLogic()

# 1. 页面路由（渲染前端 Vue 模板）
@level_editor_bp.route('/editor')
def editor_page():
    return render_template('level_editor.html')

# 2. 初始化数据接口（前端一加载页面就请求，获取英雄、场景、卡牌字典）
@level_editor_bp.route('/api/editor/init-data', methods=['GET'])
def get_init_data():
    return jsonify({
        "status": "success",
        "data": {
            "plant_heroes": [{"id": h[0], "name": h[1]} for h in PLANT_HEROES],
            "zombie_heroes": [{"id": h[0], "name": h[1]} for h in ZOMBIE_HEROES],
            "scenes": [{"id": s[0], "name": s[1]} for s in SCENES],
            "cards": logic.get_card_index(),
            "decks": logic.get_deck_db()
        }
    })

# 3. 获取 AB 包关卡列表接口
@level_editor_bp.route('/api/editor/ab/list', methods=['GET'])
def get_ab_levels():
    lock_response = acquire_unity_lock(json_response=True)
    if lock_response:
        return lock_response
    try:
        level_ids = logic.get_all_level_ids()
        return jsonify({"status": "success", "data": level_ids})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        release_unity_lock()

# 4. 提取单个关卡 JSON 接口
@level_editor_bp.route('/api/editor/ab/extract', methods=['POST'])
def extract_level():
    try:
        level_id = validate_level_id(read_json_object())
    except JsonInputError as e:
        return json_error_response(e)
    lock_response = acquire_unity_lock(json_response=True)
    if lock_response:
        return lock_response
    try:
        config_json = logic.load_level_config(level_id)
        return jsonify({"status": "success", "data": config_json})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    finally:
        release_unity_lock()

# 5. 打包并下载 AB 包接口
@level_editor_bp.route('/api/editor/ab/pack', methods=['POST'])
def pack_level():
    try:
        data = read_json_object()
        level_id = validate_level_id(data)
        config_text = serialize_level_config(data.get('config'))
    except JsonInputError as e:
        return json_error_response(e)

    lock_response = acquire_unity_lock(json_response=True)
    if lock_response:
        return lock_response
    
    workdir = None
    download_ready = False
    try:
        workdir = tempfile.mkdtemp(prefix="level_editor_")
        asset_filename = logic.asset_filename
        out_path = os.path.join(workdir, asset_filename)
        # 执行打包逻辑
        worker_output = os.path.join(workdir, "output.bundle")
        run_unity_job(workdir, "level_pack", {"level_id": level_id, "config_text": config_text})
        os.replace(worker_output, out_path)

        def cleanup():
            shutil.rmtree(workdir, ignore_errors=True)
            gc.collect()
            
        # 将打包好的文件作为附件返回给用户下载
        response = send_file(
            out_path, 
            as_attachment=True, 
            download_name=asset_filename,
            mimetype="application/octet-stream"
        )
        # 先关闭下载文件句柄再删除目录，兼容 Windows。
        response.direct_passthrough = False
        response.call_on_close(cleanup)
        download_ready = True
        return response
    except ClientFacingError as e:
        return jsonify({"status": "error", "message": str(e)}), e.status
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    finally:
        if workdir and not download_ready:
            shutil.rmtree(workdir, ignore_errors=True)
        release_unity_lock()
