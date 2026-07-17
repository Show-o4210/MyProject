#!/usr/bin/env python3
"""Build-time static sitemap/robots（线上仍以 blueprints/home.py 动态路由为准）。"""
import json
import os
from datetime import datetime, timezone


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    downloads_path = os.path.join(root_dir, "data", "downloads.json")
    static_dir = os.path.join(root_dir, "static")
    today = datetime.now(timezone.utc).date().isoformat()

    urls = [
        {"loc": "https://pvz-h-tools.onrender.com/", "changefreq": "daily", "priority": "1.0"},
        {"loc": "https://pvz-h-tools.onrender.com/downloads", "changefreq": "weekly", "priority": "0.9"},
        {"loc": "https://pvz-h-tools.onrender.com/unity", "changefreq": "weekly", "priority": "0.9"},
        {"loc": "https://pvz-h-tools.onrender.com/deck-editor", "changefreq": "weekly", "priority": "0.8"},
        {"loc": "https://pvz-h-tools.onrender.com/editor", "changefreq": "weekly", "priority": "0.8"},
        {"loc": "https://pvz-h-tools.onrender.com/phantom", "changefreq": "weekly", "priority": "0.8"},
        {"loc": "https://pvz-h-tools.onrender.com/card-sender", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "https://pvz-h-tools.onrender.com/pack-buyer", "changefreq": "monthly", "priority": "0.7"},
        {"loc": "https://pvz-h-tools.onrender.com/feedback", "changefreq": "monthly", "priority": "0.5"},
    ]

    if os.path.exists(downloads_path):
        try:
            with open(downloads_path, "r", encoding="utf-8") as f:
                catalog = json.load(f)
            sections = catalog.get("sections", [])
            for section in sections:
                for item in section.get("items", []):
                    item_id = item.get("id")
                    if item_id:
                        urls.append({
                            "loc": f"https://pvz-h-tools.onrender.com/downloads/{item_id}",
                            "changefreq": "weekly",
                            "priority": "0.6",
                        })
        except Exception as e:
            print(f"Error reading downloads.json: {e}")

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
    xml_lines.append("</urlset>")
    sitemap_content = "\n".join(xml_lines) + "\n"

    sitemap_dest = os.path.join(static_dir, "sitemap.xml")
    with open(sitemap_dest, "w", encoding="utf-8") as f:
        f.write(sitemap_content)
    print(f"Generated static sitemap.xml at {sitemap_dest}")

    robots_content = """User-agent: *
Allow: /

Disallow: /api/
Disallow: /security/

Sitemap: https://pvz-h-tools.onrender.com/sitemap.xml
"""
    robots_dest = os.path.join(static_dir, "robots.txt")
    with open(robots_dest, "w", encoding="utf-8") as f:
        f.write(robots_content)
    print(f"Generated static robots.txt at {robots_dest}")


if __name__ == "__main__":
    main()
