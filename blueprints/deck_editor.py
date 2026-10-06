from flask import Blueprint, render_template, jsonify, send_file
import os
import shutil
import tempfile
from logic_data import data_manager
from extensions import acquire_unity_lock, release_unity_lock
from utils.deck_requests import read_deck_mods
from utils.json_requests import JsonInputError, json_error_response
from utils.patch_limits import ClientFacingError
from utils.unity_jobs import run_unity_job
from blueprints.unity import register_cleanup

deck_editor_bp = Blueprint('deck_editor', __name__)
_cached_raw_decks = None


@deck_editor_bp.route('/deck-editor')
def index():
    return render_template('deck_editor.html')


@deck_editor_bp.route('/api/init_data', methods=['GET'])
def get_init_data():
    global _cached_raw_decks
    if _cached_raw_decks is None:
        busy = acquire_unity_lock(json_response=True)
        if busy:
            return busy
        try:
            if _cached_raw_decks is None:
                with tempfile.TemporaryDirectory(prefix='unity_tool_deck_init_') as workdir:
                    _cached_raw_decks = run_unity_job(workdir, 'deck_init', {})
        except ClientFacingError as exc:
            return jsonify({'status': 'error', 'msg': str(exc)}), exc.status
        finally:
            release_unity_lock()
    return jsonify({'status': 'success', 'data': {
        'hero_decks': data_manager.hero_decks, 'cards': data_manager.card_list,
        'raw_bundle_data': _cached_raw_decks,
    }})


@deck_editor_bp.route('/api/quick_export', methods=['POST'])
def quick_export():
    try:
        mods = read_deck_mods()
    except JsonInputError as exc:
        return json_error_response(exc)
    busy = acquire_unity_lock(json_response=True)
    if busy:
        return busy
    workdir = None
    download_ready = False
    try:
        workdir = tempfile.mkdtemp(prefix='unity_tool_deck_')
        run_unity_job(workdir, 'deck_export', {'mods': mods})
        response = send_file(os.path.join(workdir, 'output.zip'), mimetype='application/zip',
                             as_attachment=True, download_name='PVZH_Decks_Mod.zip')
        register_cleanup(workdir)
        download_ready = True
        return response
    except ClientFacingError as exc:
        return jsonify({'status': 'error', 'msg': str(exc), 'message': str(exc)}), exc.status
    finally:
        if workdir and not download_ready:
            shutil.rmtree(workdir, ignore_errors=True)
        release_unity_lock()
