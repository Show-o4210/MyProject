"""Read-only PVZH version service. Importing the app starts no jobs or network I/O."""
import os

from flask import Flask, jsonify, send_from_directory

from config import Config
from blueprints.featured import featured_bp
from blueprints.home import home_bp
from blueprints.launcher import launcher_bp
from blueprints.retired import retired_bp
from blueprints.sponsors import sponsors_bp
from blueprints.version import version_bp


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    for blueprint in (home_bp, version_bp, launcher_bp, featured_bp, sponsors_bp, retired_bp):
        app.register_blueprint(blueprint)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(app.static_folder, "favicon.ico", max_age=86400)

    @app.after_request
    def response_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; style-src 'self'; img-src 'self'; "
            "base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if response.status_code >= 400:
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(413)
    def too_large(_error):
        return jsonify({"error": "本站仅提供只读版本服务，不接受文件上传。"}), 413

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5001)), debug=False)
