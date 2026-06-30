from flask import Blueprint, render_template, redirect

from extensions import limiter
from utils.json_data import load_json_file

downloads_bp = Blueprint('downloads', __name__)


def load_downloads_data():
    data = load_json_file('downloads.json', default={})
    return data.get('tools', []) if isinstance(data, dict) else []


def find_tool(item_id):
    return next((tool for tool in load_downloads_data() if tool.get('id') == item_id), None)


@downloads_bp.route('/downloads')
def index():
    return render_template('tab_downloads.html', tools=load_downloads_data())


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