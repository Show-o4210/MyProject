import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, jsonify, redirect, request, url_for

from extensions import limiter
from logic_ea_api import (
    CLIENT_ID,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_CONTENT_VERSION,
    DEFAULT_PLATFORM,
    soft_purchase,
    sync_inventory,
)

pack_buyer_bp = Blueprint('pack_buyer', __name__)

PACK_JSON_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'packs.json'
)

SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,64}$")
SAFE_CONTENT_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,128}$")
SAFE_PLATFORM_RE = re.compile(r"^[0-9A-Za-z._ -]{1,32}$")


def load_packs_from_file() -> List[Dict[str, Any]]:
    if os.path.exists(PACK_JSON_FILE):
        try:
            with open(PACK_JSON_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取 packs.json 失败: {e}")
    return []


def find_pack_by_sku(sku: str) -> Optional[Dict[str, Any]]:
    sku_lower = str(sku or '').strip().lower()
    if not sku_lower:
        return None
    for pack in load_packs_from_file():
        if str(pack.get('sku', '')).strip().lower() == sku_lower:
            return pack
    return None


def clean_field(value: Any, default: str, pattern: re.Pattern) -> str:
    text = str(value or '').strip()
    if not text:
        return default
    if not pattern.match(text):
        return default
    return text


def stringify_body(body: Any) -> str:
    if isinstance(body, (dict, list)):
        try:
            return json.dumps(body, ensure_ascii=False)
        except Exception:
            return str(body)
    return str(body or '')


def humanize_pack_error(status_code: int, body: Any) -> str:
    text = stringify_body(body).lower()

    if status_code in (401, 403) or 'token' in text or 'auth' in text or 'unauthorized' in text:
        return '购买失败：Token 或 Persona ID 可能已过期/不匹配，请重新获取后再试。'
    if status_code == 404:
        return '购买失败：服务端没有找到该卡包 SKU，可能是卡包 ID 填错或卡包数据已过期。'
    if status_code == 409:
        return '购买失败：服务端认为本次购买状态冲突，可能已经购买过、库存状态未刷新，或请求参数和当前账号状态不一致。'
    if status_code == 429 or 'rate' in text or 'too many' in text:
        return '购买失败：请求过于频繁。请等待一段时间再试，避免连续点击。'
    if 'cost' in text or 'currency' in text or 'soft' in text or 'gem' in text or 'diamond' in text:
        return '购买失败：服务端认为价格或货币校验未通过。即使钻石足够，也可能是 ExpectedCost、卡包 SKU 或版本参数不匹配。'
    if 'version' in text or 'client' in text or 'content' in text:
        return '购买失败：服务端疑似拒绝当前客户端版本或内容版本。请尝试填写最新 Client Version / Content Version。'
    if status_code >= 500:
        return '购买失败：PVZH 服务端暂时异常或不可达，请稍后再试。'
    if status_code >= 400:
        return f'购买失败：PVZH 服务端拒绝了请求（HTTP {status_code}）。请检查 Token、Persona ID、SKU、价格和版本参数。'
    return '购买失败：服务端返回了非成功结果，但没有给出明确原因。请展开响应结果查看原始返回。'


@pack_buyer_bp.route('/pack-buyer')
def pack_buyer_page():
    return redirect(url_for('ea_tools.ea_tools_page', operation='packs'), code=302)


@pack_buyer_bp.route('/api/packs', methods=['GET'])
def get_packs():
    packs = load_packs_from_file()
    return jsonify({
        'success': True,
        'packs': packs,
        'total': len(packs),
    })


@pack_buyer_bp.route('/api/pack-settings', methods=['GET'])
def get_pack_settings():
    return jsonify({
        'success': True,
        'client_id': CLIENT_ID,
        'client_version': DEFAULT_CLIENT_VERSION,
        'content_version': DEFAULT_CONTENT_VERSION,
        'platform': DEFAULT_PLATFORM,
    })


@pack_buyer_bp.route('/api/buy-pack', methods=['POST'])
@limiter.limit("5 per minute")
def buy_pack():
    """购买卡包，无需登录，直接使用前端传入的 Token 和 Persona ID。"""
    data = request.get_json(silent=True) or {}

    sku = str(data.get('sku', '')).strip()
    token = str(data.get('token', '')).strip()
    persona_id = str(data.get('persona_id', '')).strip()
    raw_cost = data.get('cost', 0)

    client_version = clean_field(data.get('client_version'), DEFAULT_CLIENT_VERSION, SAFE_VERSION_RE)
    content_version = clean_field(data.get('content_version'), DEFAULT_CONTENT_VERSION, SAFE_CONTENT_VERSION_RE)
    platform = clean_field(data.get('platform'), DEFAULT_PLATFORM, SAFE_PLATFORM_RE)

    if not token:
        return jsonify({"success": False, "error": "EADP-AUTH-TOKEN 不能为空"}), 400
    if not persona_id:
        return jsonify({"success": False, "error": "EADP-PERSONA-ID 不能为空"}), 400
    if not sku:
        return jsonify({"success": False, "error": "请选择或填写卡包 SKU"}), 400

    try:
        cost = int(raw_cost)
        if cost <= 0:
            return jsonify({"success": False, "error": "卡包花费必须大于 0"}), 400
    except (ValueError, TypeError):
        return jsonify({"success": False, "error": "卡包花费必须是有效的数字"}), 400

    matched_pack = find_pack_by_sku(sku)
    warnings = []
    if matched_pack and int(matched_pack.get('cost') or 0) != cost:
        warnings.append(
            f"当前卡包列表记录的价格是 {matched_pack.get('cost')}，你提交的是 {cost}。如果价格不一致，服务端可能会拒绝购买。"
        )
    elif not matched_pack:
        warnings.append("未在本地卡包列表中找到该 SKU；如果是手动输入，请确认 SKU 和价格完全正确。")

    payload = {
        "Sku": sku,
        "EventId": None,
        "Cards": None,
        "ExpectedCost": cost,
        "KeyName": None,
    }

    try:
        response, response_body, response_text, headers = soft_purchase(
            payload,
            token,
            persona_id,
            client_version=client_version,
            content_version=content_version,
            platform=platform,
        )
        success = response.status_code == 200
        error_message = None if success else humanize_pack_error(response.status_code, response_body)

        return jsonify({
            "success": success,
            "error": error_message,
            "status_code": response.status_code,
            "response": response_body,
            "raw_response": response_text[:4000],
            "warnings": warnings,
            "request_meta": {
                "sku": sku,
                "expected_cost": cost,
                "platform": platform,
                "client_version": client_version,
                "content_version": content_version,
                "utc_ms": headers["X-Pvzh-UTC"],
            },
        })

    except requests.Timeout:
        return jsonify({"success": False, "error": "请求超时，请稍后重试"}), 504
    except requests.ConnectionError:
        return jsonify({"success": False, "error": "网络连接失败，服务器无法连接 PVZH 接口"}), 503
    except requests.RequestException as e:
        return jsonify({"success": False, "error": f"上游请求失败: {type(e).__name__}"}), 502
    except Exception:
        return jsonify({"success": False, "error": "服务器处理失败，请稍后重试"}), 500


@pack_buyer_bp.route('/api/sync-inventory', methods=['POST'])
@limiter.limit("5 per minute")
def sync_inventory_route():
    """查询账号库存及未开启卡包列表。"""
    data = request.get_json(silent=True) or {}

    token = str(data.get('token', '')).strip()
    persona_id = str(data.get('persona_id', '')).strip()

    client_version = clean_field(data.get('client_version'), DEFAULT_CLIENT_VERSION, SAFE_VERSION_RE)
    content_version = clean_field(data.get('content_version'), DEFAULT_CONTENT_VERSION, SAFE_CONTENT_VERSION_RE)
    platform = clean_field(data.get('platform'), DEFAULT_PLATFORM, SAFE_PLATFORM_RE)

    if not token:
        return jsonify({"success": False, "error": "EADP-AUTH-TOKEN 不能为空"}), 400
    if not persona_id:
        return jsonify({"success": False, "error": "EADP-PERSONA-ID 不能为空"}), 400

    try:
        response, response_body, response_text, headers = sync_inventory(
            token,
            persona_id,
            client_version=client_version,
            content_version=content_version,
            platform=platform,
        )
        success = response.status_code == 200

        inventory_summary = None
        if success and isinstance(response_body, dict):
            unopened_raw = response_body.get('UnopenedBoosterPacks') or []
            grouped_packs = {}
            for pack in unopened_raw:
                p_type = pack.get('PackTypeId', '未知卡包')
                grouped_packs[p_type] = grouped_packs.get(p_type, 0) + 1

            pack_type_map = {
                'cosmicpack': '银河补充包',
                'DoomAndBloom': '末日与绽放包',
                'Hero_HugeGigantacus_Pack': '至尊大王英雄包',
                'Hero_BetaCarrotina_Pack': '贝塔胡萝卜蒂娜英雄包',
                'goldPack': '高级补充包',
                'Set3pack': '化石补充包',
                'Set4pack': '三叠纪补充包',
            }

            pack_list = []
            for p_type, count in grouped_packs.items():
                cn_name = pack_type_map.get(p_type, p_type)
                pack_list.append({
                    'type_id': p_type,
                    'name': cn_name,
                    'count': count
                })

            inventory_summary = {
                'gems': response_body.get('totalGemBalance', 0),
                'sparks': response_body.get('Sparks', 0),
                'heroes_count': len(response_body.get('Heroes') or {}),
                'total_cards': response_body.get('totalNumCards', 0),
                'unopened_total': len(unopened_raw),
                'unopened_packs': pack_list,
            }

        error_message = None if success else f"查询失败（HTTP {response.status_code}）"

        return jsonify({
            "success": success,
            "error": error_message,
            "status_code": response.status_code,
            "inventory": inventory_summary,
            "response": response_body,
            "raw_response": response_text[:4000],
        })

    except requests.Timeout:
        return jsonify({"success": False, "error": "请求超时，请稍后重试"}), 504
    except requests.ConnectionError:
        return jsonify({"success": False, "error": "网络连接失败，服务器无法连接 PVZH 接口"}), 503
    except requests.RequestException as e:
        return jsonify({"success": False, "error": f"上游请求失败: {type(e).__name__}"}), 502
    except Exception as e:
        return jsonify({"success": False, "error": f"服务器处理失败: {e}"}), 500
