import re


def clean_json_string(s):
    """防御级 JSON 脏数据清洗：去除控制字符、BOM，替换中文标点。"""
    if not isinstance(s, str):
        return s
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    cleaned = cleaned.replace('\ufeff', '').strip()
    cleaned = cleaned.replace('\uff0c', ',').replace('\u201c', '"').replace('\u201d', '"')
    return cleaned