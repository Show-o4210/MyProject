from datetime import datetime, timezone

from flask import Blueprint, render_template, Response

from utils.json_data import load_json_file
from blueprints.downloads import load_catalog

home_bp = Blueprint('home', __name__)

SITE_ORIGIN = "https://pvz-h-tools.onrender.com"


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
    content = f"""User-agent: *
Allow: /

# API 与安全接口无公开索引价值
Disallow: /api/
Disallow: /security/

Sitemap: {SITE_ORIGIN}/sitemap.xml
"""
    return Response(content, mimetype="text/plain")


@home_bp.route('/sitemap.xml')
def sitemap_xml():
    # lastmod 使用当天 UTC 日期，便于 GSC 感知站点仍在维护
    today = datetime.now(timezone.utc).date().isoformat()

    urls = [
        {"loc": f"{SITE_ORIGIN}/", "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{SITE_ORIGIN}/downloads", "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{SITE_ORIGIN}/unity", "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{SITE_ORIGIN}/deck-editor", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{SITE_ORIGIN}/editor", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{SITE_ORIGIN}/phantom", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{SITE_ORIGIN}/card-sender", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{SITE_ORIGIN}/pack-buyer", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{SITE_ORIGIN}/feedback", "changefreq": "monthly", "priority": "0.5"},
    ]

    try:
        catalog = load_catalog()
        for section in catalog:
            for item in section.get('entries', []):
                item_id = item.get('id')
                if item_id:
                    urls.append({
                        "loc": f"{SITE_ORIGIN}/downloads/{item_id}",
                        "changefreq": "weekly",
                        "priority": "0.6",
                    })
    except Exception:
        pass

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for url in urls:
        xml_lines.append(
            "  <url>"
            f"<loc>{url['loc']}</loc>"
            f"<lastmod>{today}</lastmod>"
            f"<changefreq>{url['changefreq']}</changefreq>"
            f"<priority>{url['priority']}</priority>"
            "</url>"
        )
    xml_lines.append('</urlset>')

    return Response("\n".join(xml_lines) + "\n", mimetype="application/xml")
