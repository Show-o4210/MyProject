from flask import Blueprint, render_template, redirect, current_app
from extensions import limiter
import json
import os

downloads_bp = Blueprint('downloads', __name__)


def get_downloads_file_path():
    return os.path.join(current_app.root_path, 'data', 'downloads.json')


def load_downloads_data():
    file_path = get_downloads_file_path()

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f).get('tools', [])
    except Exception as e:
        print(f"读取下载列表失败: {e}")
        return []


def find_tool(item_id):
    tools = load_downloads_data()
    return next((tool for tool in tools if tool.get('id') == item_id), None)


@downloads_bp.route('/downloads')
def index():
    tools = load_downloads_data()
    return render_template('tab_downloads.html', tools=tools)


@downloads_bp.route('/downloads/<item_id>')
def detail(item_id):
    tool = find_tool(item_id)

    if not tool:
        return render_template('error.html', msg="未找到该资源，可能已被下架。"), 404

    return render_template('download_detail.html', tool=tool)


@downloads_bp.route('/api/download/<item_id>')
@limiter.limit("5 per minute")
def trigger_download(item_id):
    tool = find_tool(item_id)

    if not tool:
        return render_template('error.html', msg="未找到该资源，可能已被下架。"), 404

    return redirect(tool['url'])