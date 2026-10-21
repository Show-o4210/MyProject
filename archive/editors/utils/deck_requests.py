"""Small, typed custom-deck requests; no Unity work during validation."""
import json
from flask import request
from werkzeug.exceptions import RequestEntityTooLarge
from logic_data import data_manager
from utils.json_requests import JsonInputError

BODY_BYTES = 512 * 1024
MAX_DECKS = 110
MAX_ENTRIES = 128  # Custom Mod decks, not a tournament deck-rule validator.
MAX_TOTAL_ENTRIES = 8192
MAX_COPIES = 99


def validate_mods(mods):
    if not isinstance(mods, dict) or not mods:
        raise JsonInputError('卡组修改必须是非空 JSON 对象')
    if len(mods) > MAX_DECKS:
        raise JsonInputError('一次修改的卡组过多', 413)
    known_cards = {card['CardGuid']: card['Faction'] for card in data_manager.card_list}
    total = 0
    clean = {}
    for deck_id, entries in mods.items():
        if deck_id not in data_manager.valid_eng_ids:
            raise JsonInputError('包含未知卡组 ID')
        if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
            raise JsonInputError('单个卡组条目必须是数组且不能超过 128 项', 413)
        total += len(entries)
        if total > MAX_TOTAL_ENTRIES:
            raise JsonInputError('修改的卡牌条目总数过多', 413)
        cards = []
        seen = set()
        for entry in entries:
            if not isinstance(entry, dict) or set(entry) != {'cardguid', 'count', 'faction'}:
                raise JsonInputError('卡牌条目字段无效')
            guid, count, faction = entry['cardguid'], entry['count'], entry['faction']
            if type(guid) is not int or guid not in known_cards or guid in seen:
                raise JsonInputError('卡牌 ID 未知或重复')
            if type(count) is not int or not 1 <= count <= MAX_COPIES:
                raise JsonInputError('卡牌数量必须为 1–99 的整数')
            if type(faction) is not int or faction != known_cards[guid]:
                raise JsonInputError('卡牌阵营无效')
            seen.add(guid)
            cards.append({'cardguid': guid, 'count': count, 'faction': faction})
        clean[deck_id] = cards
    return clean


def read_deck_mods():
    request.max_content_length = min(request.max_content_length or BODY_BYTES, BODY_BYTES)
    request.max_form_memory_size = BODY_BYTES
    request.max_form_parts = 2
    try:
        if request.content_length is not None and request.content_length > BODY_BYTES:
            raise RequestEntityTooLarge()
        if request.mimetype not in {'multipart/form-data', 'application/x-www-form-urlencoded'}:
            raise JsonInputError('请使用表单提交卡组 JSON')
        raw = request.form.get('deck_json')
        if not raw or len(request.form.getlist('deck_json')) != 1 or request.files or set(request.form) != {'deck_json'}:
            raise JsonInputError('请提交唯一的 deck_json 字段')
        mods = json.loads(raw)
    except RequestEntityTooLarge as exc:
        raise JsonInputError('卡组请求不能超过 512 KiB', 413) from exc
    except (ValueError, RecursionError) as exc:
        raise JsonInputError('卡组 JSON 格式错误或嵌套过深') from exc
    return validate_mods(mods)
