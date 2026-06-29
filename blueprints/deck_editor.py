# blueprints/deck_editor.py
from flask import Blueprint, render_template, jsonify, request, send_file
import json
from logic_data import data_manager
from logic_unity import unity_processor

deck_editor_bp = Blueprint('deck_editor', __name__)

@deck_editor_bp.route('/deck-editor')
def index():
    return render_template('deck_editor.html')

@deck_editor_bp.route('/api/init_data', methods=['GET'])
def get_init_data():
    decks_content = unity_processor.extract_all_to_memory()
    return jsonify({
        "status": "success",
        "data": {
            "hero_decks": data_manager.hero_decks,
            "cards": data_manager.card_list,
            "raw_bundle_data": decks_content
        }
    })

@deck_editor_bp.route('/api/quick_export', methods=['POST'])
def quick_export():
    deck_json_str = request.form.get('deck_json')
    if not deck_json_str:
        return jsonify({"status": "error", "msg": "未检测到本地修改"}), 400
    try:
        mods = json.loads(deck_json_str)
        zip_stream = unity_processor.repack_from_server_data(mods)
        return send_file(zip_stream, mimetype='application/zip', as_attachment=True, download_name="PVZH_Decks_Mod.zip")
    except Exception as e:
        return jsonify({"status": "error", "msg": f"打包失败: {e}"}), 500