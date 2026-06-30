from __future__ import annotations

import json
import tempfile
from pathlib import Path

from flask import Blueprint, after_this_request, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

from logic_phantom_config import load_phantom_config
from logic_phantom_bundle import diff_card_data, inspect_bundle_cards, update_bundle_with_card_data

phantom_bp = Blueprint("phantom", __name__)


@phantom_bp.route("/phantom")
def phantom_page():
    """Phantom 卡牌工坊 Web GUI。

    v0.4 接入工程 card_data JSON 对 Unity AssetBundle 的注入与下载。
    """
    return render_template("phantom.html")


@phantom_bp.route("/api/phantom/ping")
def phantom_ping():
    """预留 API，用于前端确认模块已挂载。"""
    return jsonify({"ok": True, "module": "phantom", "stage": "field-ability-complete-v09"})


@phantom_bp.route("/api/phantom/config")
def phantom_config():
    """返回 Phantom 前端需要的只读资源配置。"""
    return jsonify(load_phantom_config())




@phantom_bp.route("/api/phantom/validate-project", methods=["POST"])
def phantom_validate_project():
    """校验当前 Phantom 工程生成的 cards_json。"""
    payload = request.get_json(silent=True) or {}
    cards_json = payload.get("cards_json") or {}
    if not isinstance(cards_json, dict):
        return jsonify({"ok": False, "message": "cards_json 必须是对象。"}), 400

    errors = []
    warnings = []
    seen = set()
    valid_count = 0

    for guid, entry in cards_json.items():
        guid_str = str(guid).strip()
        if not guid_str:
            errors.append({"guid": guid_str, "field": "GUID", "message": "存在空 GUID 条目。"})
            continue
        if guid_str in seen:
            errors.append({"guid": guid_str, "field": "GUID", "message": "GUID 重复。"})
        seen.add(guid_str)
        if not guid_str.isdigit():
            warnings.append({"guid": guid_str, "field": "GUID", "message": "GUID 不是纯数字，可能无法被游戏正确读取。"})
        if not isinstance(entry, dict):
            errors.append({"guid": guid_str, "field": "entry", "message": "卡牌条目不是对象。"})
            continue
        valid_count += 1
        if not entry.get("prefabName"):
            warnings.append({"guid": guid_str, "field": "prefabName", "message": "PrefabName 为空，除非你确定使用原资源，否则可能无法显示。"})
        if not entry.get("baseId"):
            errors.append({"guid": guid_str, "field": "baseId", "message": "缺少 baseId。"})
        if not entry.get("entity") or not isinstance(entry.get("entity"), dict):
            errors.append({"guid": guid_str, "field": "entity", "message": "缺少 entity 对象。"})
        components = entry.get("entity", {}).get("components") if isinstance(entry.get("entity"), dict) else None
        if not isinstance(components, list) or not components:
            errors.append({"guid": guid_str, "field": "components", "message": "缺少 entity.components 组件列表。"})
        else:
            component_types = [str(item.get("$type", "")) for item in components if isinstance(item, dict)]
            if not any("Card" in item for item in component_types):
                errors.append({"guid": guid_str, "field": "components", "message": "组件列表中未发现 Card 组件。"})
            if not any("Rarity" in item for item in component_types):
                warnings.append({"guid": guid_str, "field": "components", "message": "组件列表中未发现 Rarity 组件。"})
        for field in ["displaySunCost", "displayAttack", "displayHealth", "rarity"]:
            if field in entry and not isinstance(entry.get(field), (int, float)):
                warnings.append({"guid": guid_str, "field": field, "message": f"{field} 不是数字。"})

    ok = not errors
    return jsonify({
        "ok": ok,
        "message": "工程校验通过。" if ok else "工程校验发现错误。",
        "summary": {"cards": valid_count, "errors": len(errors), "warnings": len(warnings)},
        "errors": errors,
        "warnings": warnings,
    })


@phantom_bp.route("/api/phantom/inspect-bundle", methods=["POST"])
def phantom_inspect_bundle():
    """上传原始 AssetBundle，预检是否存在可解析的 cards 资源。"""
    bundle_file = request.files.get("bundle")
    if not bundle_file or not bundle_file.filename:
        return jsonify({"ok": False, "message": "请先上传原始 AssetBundle 文件。"}), 400

    target_asset_name = (request.form.get("target_asset_name") or "cards").strip() or "cards"
    safe_input_name = secure_filename(bundle_file.filename) or "input_bundle"
    suffix = Path(safe_input_name).suffix

    with tempfile.TemporaryDirectory(prefix="phantom_inspect_") as tmp_dir:
        input_path = Path(tmp_dir) / f"input{suffix}"
        bundle_file.save(input_path)
        ok, message, detail = inspect_bundle_cards(input_path, target_asset_name=target_asset_name, include_data=False)

    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message, "detail": detail}), status


@phantom_bp.route("/api/phantom/diff", methods=["POST"])
def phantom_diff_cards():
    """对比原始 card_data 与当前工程 card_data。支持直接上传 JSON 或上传 AB 包读取。"""
    cards_json_raw = request.form.get("cards_json", "")
    if not cards_json_raw:
        return jsonify({"ok": False, "message": "缺少当前工程 cards_json。"}), 400
    try:
        modded_data = json.loads(cards_json_raw)
    except json.JSONDecodeError as exc:
        return jsonify({"ok": False, "message": f"当前工程 cards_json 不是合法 JSON：{exc}"}), 400

    original_data = None
    original_json_raw = request.form.get("original_json", "")
    if original_json_raw:
        try:
            original_data = json.loads(original_json_raw)
        except json.JSONDecodeError as exc:
            return jsonify({"ok": False, "message": f"原始 card_data JSON 不是合法 JSON：{exc}"}), 400

    bundle_file = request.files.get("bundle")
    if original_data is None and bundle_file and bundle_file.filename:
        target_asset_name = (request.form.get("target_asset_name") or "cards").strip() or "cards"
        safe_input_name = secure_filename(bundle_file.filename) or "input_bundle"
        suffix = Path(safe_input_name).suffix
        with tempfile.TemporaryDirectory(prefix="phantom_diff_") as tmp_dir:
            input_path = Path(tmp_dir) / f"input{suffix}"
            bundle_file.save(input_path)
            ok, message, detail = inspect_bundle_cards(input_path, target_asset_name=target_asset_name, include_data=True)
            if not ok:
                return jsonify({"ok": False, "message": message, "detail": detail}), 400
            original_data = detail.get("card_data")

    if original_data is None:
        return jsonify({"ok": False, "message": "请上传原始 card_data JSON，或上传可解析的原始 AB 包。"}), 400
    if not isinstance(original_data, dict) or not isinstance(modded_data, dict):
        return jsonify({"ok": False, "message": "原始数据和当前工程数据都必须是 JSON 对象。"}), 400

    diff = diff_card_data(original_data, modded_data)
    return jsonify({"ok": True, "message": "差异计算完成。", "diff": diff})


@phantom_bp.route("/api/phantom/pack", methods=["POST"])
def phantom_pack_bundle():
    """上传原始 AssetBundle，并把当前工程生成的 card_data JSON 注入进去。

    表单字段：
    - bundle: 原始 AB 包文件
    - cards_json: 前端生成的 {GUID: card_entry} JSON 字符串
    - target_asset_name: 目标资源名关键字，默认 cards
    - output_name: 下载文件名，默认 phantom_cards_bundle
    """
    bundle_file = request.files.get("bundle")
    if not bundle_file or not bundle_file.filename:
        return jsonify({"ok": False, "message": "请先上传原始 AssetBundle 文件。"}), 400

    cards_json_raw = request.form.get("cards_json", "")
    if not cards_json_raw:
        return jsonify({"ok": False, "message": "缺少 cards_json。请先生成当前工程卡牌 JSON。"}), 400

    try:
        card_data = json.loads(cards_json_raw)
    except json.JSONDecodeError as exc:
        return jsonify({"ok": False, "message": f"cards_json 不是合法 JSON：{exc}"}), 400

    if not isinstance(card_data, dict) or not card_data:
        return jsonify({"ok": False, "message": "当前工程没有可注入的卡牌数据。"}), 400

    target_asset_name = (request.form.get("target_asset_name") or "cards").strip() or "cards"
    output_name = secure_filename((request.form.get("output_name") or "phantom_cards_bundle").strip()) or "phantom_cards_bundle"
    if output_name.lower().endswith(".json"):
        output_name = output_name[:-5]
    if output_name.lower().endswith(".zip"):
        output_name = output_name[:-4]

    safe_input_name = secure_filename(bundle_file.filename) or "input_bundle"
    suffix = Path(safe_input_name).suffix

    with tempfile.TemporaryDirectory(prefix="phantom_pack_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / f"input{suffix}"
        output_path = tmp_path / output_name
        bundle_file.save(input_path)

        ok, message, detail = update_bundle_with_card_data(
            input_path,
            output_path,
            card_data,
            target_asset_name=target_asset_name,
        )
        if not ok:
            return jsonify({"ok": False, "message": message, "detail": detail}), 400

        # send_file 会在响应期间读取文件；TemporaryDirectory 在函数返回后关闭不安全。
        # 因此复制到 NamedTemporaryFile(delete=False)，并让 Flask 读取该路径。
        final_tmp = tempfile.NamedTemporaryFile(prefix="phantom_bundle_", suffix=".bundle", delete=False)
        final_tmp.close()
        final_path = Path(final_tmp.name)
        final_path.write_bytes(output_path.read_bytes())

    @after_this_request
    def cleanup_temp_file(response):
        try:
            final_path.unlink(missing_ok=True)
        except Exception:
            pass
        return response

    download_name = output_name
    return send_file(
        final_path,
        as_attachment=True,
        download_name=download_name,
        mimetype="application/octet-stream",
        max_age=0,
    )
