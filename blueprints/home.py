from flask import Blueprint, render_template

from utils.json_data import load_json_file

home_bp = Blueprint('home', __name__)


def load_news_data():
    data = load_json_file('news.json', default={})
    return {
        'announcements': data.get('announcements', []),
        'changelogs': data.get('changelogs', []),
    }


@home_bp.route('/')
def index():
    news_data = load_news_data()
    return render_template(
        'index.html',
        current_tab='home',
        announcements=news_data['announcements'],
        changelogs=news_data['changelogs'],
    )


@home_bp.route('/tools')
def tools():
    return render_template('tab_coming_soon.html', current_tab='tools')