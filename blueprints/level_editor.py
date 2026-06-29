# blueprints/level_editor.py
from flask import Blueprint, render_template, jsonify, request, send_file
from logic_level_editor import LevelEditorLogic

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
    try:
        level_ids = logic.get_all_level_ids()
        return jsonify({"status": "success", "data": level_ids})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# 4. 提取单个关卡 JSON 接口
@level_editor_bp.route('/api/editor/ab/extract', methods=['POST'])
def extract_level():
    data = request.json
    level_id = data.get('level_id')
    if not level_id:
        return jsonify({"status": "error", "message": "缺失 level_id"}), 400
    
    try:
        config_json = logic.load_level_config(level_id)
        return jsonify({"status": "success", "data": config_json})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400

# 5. 打包并下载 AB 包接口
@level_editor_bp.route('/api/editor/ab/pack', methods=['POST'])
def pack_level():
    data = request.json
    level_id = data.get('level_id')
    config_dict = data.get('config')
    
    if not level_id or not config_dict:
        return jsonify({"status": "error", "message": "缺少必要的参数"}), 400
        
    try:
        # 执行打包逻辑
        out_path = logic.pack_level_config(level_id, config_dict)
        
        # 将打包好的文件作为附件返回给用户下载
        return send_file(
            out_path, 
            as_attachment=True, 
            download_name="data_assets_36",
            mimetype="application/octet-stream"
        )
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500