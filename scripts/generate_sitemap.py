#!/usr/bin/env python3
"""
Build-time 生成 static/sitemap.xml 与 static/robots.txt 快照。

线上爬虫访问的是根路径 /robots.txt、/sitemap.xml，由 blueprints/home.py
动态路由提供（WhiteNoise 只挂 /static/，不会自动映射根路径）。
本脚本便于本地预览、仓库内快照与离线校验，改下载目录后请重跑。
"""
import json
import os
from datetime import datetime, timezone


def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    downloads_path = os.path.join(root_dir, "data", "downloads.json")
    static_dir = os.path.join(root_dir, "static")
    today = datetime.now(timezone.utc).date().isoformat()
    base = os.environ.get("SITE_BASE_URL", "https://pvz-h-tools.onrender.com").rstrip("/")

    urls = [
        {"loc": f"{base}/", "changefreq": "daily", "priority": "1.0"},
        {"loc": f"{base}/downloads", "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base}/unity", "changefreq": "weekly", "priority": "0.9"},
        {"loc": f"{base}/deck-editor", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/editor", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/phantom", "changefreq": "weekly", "priority": "0.8"},
        {"loc": f"{base}/card-sender", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base}/pack-buyer", "changefreq": "monthly", "priority": "0.7"},
        {"loc": f"{base}/feedback", "changefreq": "monthly", "priority": "0.5"},
        {"loc": f"{base}/tools", "changefreq": "monthly", "priority": "0.5"},
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
                            "loc": f"{base}/downloads/{item_id}",
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

    robots_content = f"""User-agent: *
Allow: /

Disallow: /api/
Disallow: /security/

Sitemap: {base}/sitemap.xml
"""
    robots_dest = os.path.join(static_dir, "robots.txt")
    with open(robots_dest, "w", encoding="utf-8") as f:
        f.write(robots_content)
    print(f"Generated static robots.txt at {robots_dest}")
    print("Note: production bots hit /robots.txt and /sitemap.xml via home_bp routes, not /static/.")


if __name__ == "__main__":
    main()
