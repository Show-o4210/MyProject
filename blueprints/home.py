from flask import Blueprint, render_template, request

from utils.home_tabs import normalize_home_tab
from utils.json_data import load_json_file

home_bp = Blueprint('home', __name__)


def load_news_data():
    data = load_json_file('news.json', default={})
    return {
        'announcements': data.get('announcements', []),
        'changelogs': data.get('changelogs', []),
    }


def load_download_tools():
    data = load_json_file('downloads.json', default={})
    return data.get('tools', []) if isinstance(data, dict) else []


@home_bp.route('/')
def index():
    news_data = load_news_data()
    return render_template(
        'index.html',
        current_tab='home',
        initial_tab=normalize_home_tab(request.args.get('tab')),
        announcements=news_data['announcements'],
        changelogs=news_data['changelogs'],
        download_tools=load_download_tools(),
    )


@home_bp.route('/tools')
def tools():
    return render_template('tab_coming_soon.html', current_tab='tools')