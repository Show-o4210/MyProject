"""The only public website page is the transition notice."""
from xml.sax.saxutils import escape

from flask import Blueprint, Response, current_app, render_template

home_bp = Blueprint("home", __name__)


@home_bp.get("/")
def index():
    response = Response(render_template("index.html"))
    response.headers["Cache-Control"] = "no-cache"
    return response


@home_bp.get("/robots.txt")
def robots_txt():
    base = current_app.config["SITE_BASE_URL"]
    return Response(
        f"User-agent: *\nAllow: /\nDisallow: /api/\n\nSitemap: {base}/sitemap.xml\n",
        mimetype="text/plain",
    )


@home_bp.get("/sitemap.xml")
def sitemap_xml():
    location = escape(current_app.config["SITE_BASE_URL"] + "/")
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{location}</loc></url></urlset>\n",
        mimetype="application/xml",
    )
