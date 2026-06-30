import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from flask import Blueprint, jsonify, render_template, request

from extensions import limiter
from logic_ea_api import (
    CLIENT_ID,
    DEFAULT_CLIENT_VERSION,
    DEFAULT_CONTENT_VERSION,
    DEFAULT_PLATFORM,
    DEFAULT_REQUEST_TIMEOUT,
    build_pvzh_headers,
    post_soft_purchase,
)

pack_buyer_bp = Blueprint('pack_buyer', __name__)

PACK_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), 'data', 'name_id_cost.txt'
)

SAFE_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,64}$")
SAFE_CONTENT_VERSION_RE = re.compile(r"^[0-9A-Za-z._-]{1,128}$")
SAFE_PLATFORM_RE = re.compile(r"^[0-9A-Za-z._ -]{1,32}$")


def load_packs_from_file() -> List[Dict[str, Any]]:
    packs: List[Dict[str, Any]] = []
    if not os.path.exists(PACK_DATA_FILE):
        return packs

    try:
        with open(PACK_DATA_FILE, 'r', encoding='utf-8') as f:
            lines = [line.strip() for line in f.readlines()]

        i = 0
        while i < len(lines):
            if not lines[i].startswith('['):
                i += 1
                continue

            block = lines[i:i + 4]
            if len(block) < 4:
                break

            try:
                index = int(block[0].strip('[]'))
                name = block[1].split(':', 1)[1].strip()
                sku = block[2].split(':', 1)[1].strip()
                cost = int(block[3].split(':', 1)[1].strip())
                packs.append({
                    'index': index,
                    'name': name,
                    'sku': sku,
                    'cost': cost,
                })
            except (ValueError, IndexError) as e:
                print(f"解析卡包数据出错: {e}")
            i += 4

        return packs
    except Exception as e:
        print(f"读取卡包文件失败: {e}")
        return packs


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


def parse_upstream_body(response: requests.Response) -> Tuple[Any, str]:
    response_text = response.text or ''
    try:
        return response.json(), response_text
    except Exception:
        try:
            return json.loads(response_text), response_text
        except Exception:
            return response_text, response_text


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
    return render_template('pack_buyer.html', current_tab='pack_buyer')


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

    headers = build_pvzh_headers(
        token,
        persona_id,
        client_version=client_version,
        content_version=content_version,
        platform=platform,
    )
    utc_ms = headers["X-Pvzh-UTC"]

    try:
        response = post_soft_purchase(payload, headers, timeout=DEFAULT_REQUEST_TIMEOUT)

        response_body, response_text = parse_upstream_body(response)
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
                "utc_ms": utc_ms,
            },
        })

    except requests.Timeout:
        return jsonify({"success": False, "error": "请求超时，请稍后重试"}), 504
    except requests.ConnectionError:
        return jsonify({"success": False, "error": "网络连接失败，服务器无法连接 PVZH 接口"}), 503
    except Exception as e:
        return jsonify({"success": False, "error": f"请求失败: {str(e)}"}), 500