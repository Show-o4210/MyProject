#!/usr/bin/env python3
import json
import os

def main():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    downloads_path = os.path.join(root_dir, "data", "downloads.json")
    static_dir = os.path.join(root_dir, "static")
    
    # 1. Generate sitemap.xml content
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
                            "priority": "0.6"
                        })
        except Exception as e:
            print(f"Error reading downloads.json: {e}")
            
    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    ]
    for url in urls:
        xml_lines.append(
            f"  <url><loc>{url['loc']}</loc><changefreq>{url['changefreq']}</changefreq><priority>{url['priority']}</priority></url>"
        )
    xml_lines.append('</urlset>')
    sitemap_content = "\n".join(xml_lines) + "\n"
    
    sitemap_dest = os.path.join(static_dir, "sitemap.xml")
    with open(sitemap_dest, "w", encoding="utf-8") as f:
        f.write(sitemap_content)
    print(f"Generated static sitemap.xml at {sitemap_dest}")

    # 2. Generate robots.txt content
    robots_content = """User-agent: *
Allow: /

Sitemap: https://pvz-h-tools.onrender.com/sitemap.xml
"""
    robots_dest = os.path.join(static_dir, "robots.txt")
    with open(robots_dest, "w", encoding="utf-8") as f:
        f.write(robots_content)
    print(f"Generated static robots.txt at {robots_dest}")

if __name__ == "__main__":
    main()
