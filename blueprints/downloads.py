from flask import Blueprint, render_template, redirect, request, url_for

from extensions import limiter
from utils.json_data import load_json_file

downloads_bp = Blueprint('downloads', __name__)

# 分区默认顺序：先展示产品向的 Mod，再是工具与资源
DEFAULT_SECTION_ID = 'mods'

def normalize_file(raw):
    """规范化 bundle 子文件；无效项返回 None。"""
    if not isinstance(raw, dict) or not raw.get('id'):
        return None
    url = (raw.get('url') or '').strip()
    file_id = raw['id']
    notes = raw.get('notes') if isinstance(raw.get('notes'), list) else []
    return {
        'id': file_id,
        'name': raw.get('name') or file_id,
        'description': raw.get('description') or '',
        'url': url,
        'size': raw.get('size') or '',
        'tag': raw.get('tag') or '',
        'updated_at': raw.get('updated_at') or '',
        'recommended': bool(raw.get('recommended')),
        'notes': notes,
    }


def normalize_item(raw):
    """
    规范化条目：
    - 有非空 files → kind=bundle
    - 否则 kind=single（兼容旧数据）
    - bundle 的 files 内 recommended 优先排序
    """
    if not isinstance(raw, dict) or not raw.get('id'):
        return None

    item = dict(raw)
    item_id = item['id']

    files_raw = item.get('files')
    files = []
    if isinstance(files_raw, list):
        for entry in files_raw:
            normalized = normalize_file(entry)
            if normalized:
                files.append(normalized)

    if files:
        files.sort(key=lambda f: (0 if f.get('recommended') else 1))

    explicit_kind = (item.get('kind') or '').strip().lower()
    if files:
        kind = 'bundle'
    elif explicit_kind == 'bundle':
        kind = 'bundle'
    else:
        kind = 'single'

    images = item.get('images') if isinstance(item.get('images'), list) else []
    cover = (item.get('cover') or '').strip()
    if not cover and images:
        first = images[0]
        if isinstance(first, str) and first.strip():
            cover = first.strip()

    item['kind'] = kind
    item['files'] = files
    item['file_count'] = len(files)
    item['images'] = images
    item['cover'] = cover
    item['series_id'] = (item.get('series_id') or '').strip()
    item['series_name'] = (item.get('series_name') or '').strip()
    try:
        item['series_order'] = int(item['series_order']) if item.get('series_order') is not None else None
    except (TypeError, ValueError):
        item['series_order'] = None

    item['default_download_url'] = resolve_download_url(item)
    return item


def resolve_download_url(item):
    """
    解析条目级默认下载 URL：
    1. item.url
    2. 首个 recommended 且有 url 的 file
    3. 仅 1 个 file 时用该 file.url
    4. 否则 None
    """
    if not isinstance(item, dict):
        return None

    direct = (item.get('url') or '').strip()
    if direct:
        return direct

    files = item.get('files') or []
    if not isinstance(files, list):
        return None

    for f in files:
        if isinstance(f, dict) and f.get('recommended') and (f.get('url') or '').strip():
            return f['url'].strip()

    valid = [f for f in files if isinstance(f, dict) and (f.get('url') or '').strip()]
    if len(valid) == 1:
        return valid[0]['url'].strip()

    return None


def load_catalog():
    """读取 downloads.json，返回规范化后的分区目录。

    注意：分区条目列表使用键名 ``entries``（而非 items），
    避免 Jinja2 访问 dict.items 方法导致 TypeError。
    JSON 文件中仍使用 ``items`` 字段。
    """
    data = load_json_file('downloads.json', default={})
    if not isinstance(data, dict):
        return []

    sections = data.get('sections')
    if isinstance(sections, list) and sections:
        normalized = []
        for section in sections:
            if not isinstance(section, dict) or not section.get('id'):
                continue
            items_raw = section.get('items') or []
            if not isinstance(items_raw, list):
                items_raw = []
            entries = []
            for raw in items_raw:
                item = normalize_item(raw)
                if item:
                    entries.append(item)
            normalized.append({
                'id': section['id'],
                'name': section.get('name') or section['id'],
                'description': section.get('description') or '',
                'icon': section.get('icon') or 'inventory_2',
                'empty_title': section.get('empty_title') or '暂时没有可用内容',
                'empty_hint': section.get('empty_hint') or '列表为空，请稍后再来。',
                'entries': entries,
            })
        return normalized

    legacy_tools = data.get('tools')
    if isinstance(legacy_tools, list):
        entries = []
        for raw in legacy_tools:
            item = normalize_item(raw)
            if item:
                entries.append(item)
        return [
            {
                'id': 'mods',
                'name': 'Mod 内容',
                'description': '面向游玩与体验的成品 Mod。',
                'icon': 'extension',
                'empty_title': '暂无 Mod 作品',
                'empty_hint': 'Mod 分区已就绪。后续将在此展示可安装的成品内容。',
                'entries': [],
            },
            {
                'id': 'tools',
                'name': '工具与资源',
                'description': '面向制作与运维的辅助软件与资源文件。',
                'icon': 'build',
                'empty_title': '暂无工具与资源',
                'empty_hint': '工具与资源列表为空，请稍后再来。',
                'entries': entries,
            },
        ]

    return []


def find_section(section_id):
    return next((s for s in load_catalog() if s.get('id') == section_id), None)


def find_item(item_id):
    """按 id 查找条目，返回 (item, section) 或 (None, None)。"""
    for section in load_catalog():
        for item in section.get('entries') or []:
            if item.get('id') == item_id:
                return item, section
    return None, None


def find_file(item_id, file_id):
    """在指定条目内查找子文件，返回 (file, item, section) 或 (None, None, None)。"""
    item, section = find_item(item_id)
    if not item:
        return None, None, None
    for f in item.get('files') or []:
        if f.get('id') == file_id:
            return f, item, section
    return None, item, section


def find_series_siblings(item):
    """同 series_id 的其它作品，按 series_order、名称排序。"""
    series_id = (item or {}).get('series_id') or ''
    if not series_id:
        return []

    siblings = []
    for section in load_catalog():
        for other in section.get('entries') or []:
            if other.get('series_id') != series_id:
                continue
            if other.get('id') == item.get('id'):
                continue
            siblings.append({
                **other,
                '_section_id': section.get('id'),
                '_section_name': section.get('name'),
            })

    def sort_key(x):
        order = x.get('series_order')
        order_val = order if isinstance(order, int) else 10**9
        return (order_val, (x.get('name') or '').lower())

    siblings.sort(key=sort_key)
    return siblings


def resolve_section_id(section_id):
    catalog = load_catalog()
    if not catalog:
        return DEFAULT_SECTION_ID
    if section_id and any(s['id'] == section_id for s in catalog):
        return section_id
    if any(s['id'] == DEFAULT_SECTION_ID for s in catalog):
        return DEFAULT_SECTION_ID
    return catalog[0]['id']


@downloads_bp.route('/downloads')
def index():
    catalog = load_catalog()
    active_id = resolve_section_id(request.args.get('section'))
    active_section = find_section(active_id) or (catalog[0] if catalog else None)

    return render_template(
        'tab_downloads.html',
        sections=catalog,
        active_section=active_section,
        active_section_id=active_id,
    )


@downloads_bp.route('/downloads/<item_id>')
def detail(item_id):
    if find_section(item_id):
        return redirect(url_for('downloads.index', section=item_id))

    item, section = find_item(item_id)
    if not item:
        return render_template('error.html', msg="未找到该资源，可能已被下架。"), 404

    series_siblings = find_series_siblings(item)

    return render_template(
        'download_detail.html',
        tool=item,
        section=section,
        series_siblings=series_siblings,
    )


@downloads_bp.route('/api/download/<item_id>')
@limiter.limit("5 per minute")
def trigger_download(item_id):
    item, _section = find_item(item_id)
    if not item:
        return render_template('error.html', msg="未找到该资源，可能已被下架。"), 404

    url = item.get('default_download_url') or resolve_download_url(item)
    if not url:
        if item.get('kind') == 'bundle':
            return redirect(url_for('downloads.detail', item_id=item_id))
        return render_template('error.html', msg="未找到该资源，可能已被下架。"), 404

    return redirect(url)


@downloads_bp.route('/api/download/<item_id>/<file_id>')
@limiter.limit("5 per minute")
def trigger_file_download(item_id, file_id):
    file_entry, item, _section = find_file(item_id, file_id)
    if not item:
        return render_template('error.html', msg="未找到该资源，可能已被下架。"), 404
    if not file_entry or not (file_entry.get('url') or '').strip():
        return render_template('error.html', msg="未找到该文件，可能已被下架。"), 404

    return redirect(file_entry['url'].strip())
