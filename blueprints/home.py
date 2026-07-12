from flask import Blueprint, render_template, Response

from utils.json_data import load_json_file
from blueprints.downloads import load_catalog

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


@home_bp.route('/robots.txt')
def robots_txt():
    content = """User-agent: *
Allow: /

Sitemap: https://pvz-h-tools.onrender.com/sitemap.xml
"""
    return Response(content, mimetype="text/plain")


@home_bp.route('/sitemap.xml')
def sitemap_xml():
    urls = [
        {"loc": "https://pvz-h-tools.onrender.com/", "changefreq": "daily", "priority": "1.0"},
        {"loc": "https://pvz-h-tools.onrender.com/downloads", "changefreq": "weekly", "priority": "0.8"},
        {"loc": "https://pvz-h-tools.onrender.com/deck-editor", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "https://pvz-h-tools.onrender.com/editor", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "https://pvz-h-tools.onrender.com/phantom", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "https://pvz-h-tools.onrender.com/unity", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "https://pvz-h-tools.onrender.com/card-sender", "changefreq": "monthly", "priority": "0.6"},
        {"loc": "https://pvz-h-tools.onrender.com/pack-buyer", "changefreq": "monthly", "priority": "0.6"},
        {"loc": "https://pvz-h-tools.onrender.com/feedback", "changefreq": "monthly", "priority": "0.5"},
    ]
    
    # 动态把下载中心的各个 Mod 详情页添加进去
    try:
        catalog = load_catalog()
        for section in catalog:
            for item in section.get('entries', []):
                item_id = item.get('id')
                if item_id:
                    urls.append({
                        "loc": f"https://pvz-h-tools.onrender.com/downloads/{item_id}",
                        "changefreq": "weekly",
                        "priority": "0.6"
                    })
    except Exception as e:
        pass

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for url in urls:
        xml_lines.append(
            f"  <url><loc>{url['loc']}</loc><changefreq>{url['changefreq']}</changefreq><priority>{url['priority']}</priority></url>"
        )
    xml_lines.append('</urlset>')
    
    return Response("\n".join(xml_lines), mimetype="application/xml")