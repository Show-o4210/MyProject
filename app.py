# app.py
import datetime
import os

import requests
from flask import Flask, send_from_directory
from flask_apscheduler import APScheduler
from whitenoise import WhiteNoise

from config import Config
from extensions import init_limiter
from security import init_security_handlers
from blueprints.unity import unity_bp
from blueprints.home import home_bp
from blueprints.deck_editor import deck_editor_bp
from blueprints.card_sender import card_sender_bp
from blueprints.pack_buyer import pack_buyer_bp
from blueprints.downloads import downloads_bp
from blueprints.level_editor import level_editor_bp
from blueprints.feedback import feedback_bp
from blueprints.phantom import phantom_bp

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config.from_object(Config)

# WhiteNoise：正确设置 Content-Length / 缓存头，避免 Gunicorn access log
# 把静态文件记成「200 0」（sendfile 无长度时常见假象），并提升 js/css/png 可靠性。
app.wsgi_app = WhiteNoise(
    app.wsgi_app,
    root=os.path.join(app.root_path, "static"),
    prefix="static/",
    max_age=60 * 60 * 24 * 7,
)

init_security_handlers(app)
init_limiter(app)

# --- 唤醒逻辑开始 ---
# 说明：Render free tier 会休眠；进程内定时请求公网 URL 保活。
# 必须打 /health（已在 security 白名单），并带专用 UA/Token，
# 否则出站 IP（如 74.220.49.7）会被当成“脚本 UA”写入安全日志。
# 全天保活：减少 Googlebot 夜间抓取撞冷启动 → 软 404 / 索引失败。
scheduler = APScheduler()

# 与 security.py 中 SELF_PING_UA / X-Self-Ping-Token 约定一致
SELF_PING_UA = "PVZH-KeepAlive/1.0"
DEFAULT_SELF_PING_URL = "https://pvz-h-tools.onrender.com/health"


def keep_awake():
    """自唤醒任务：全天每 14 分钟请求一次，降低 Free 休眠与 SEO 冷启动问题。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    url = os.environ.get("SELF_PING_URL", DEFAULT_SELF_PING_URL)
    headers = {"User-Agent": SELF_PING_UA}
    token = os.environ.get("SELF_PING_TOKEN", "").strip()
    if token:
        headers["X-Self-Ping-Token"] = token
    try:
        response = requests.get(url, headers=headers, timeout=10)
        print(f"[{now}] Self-ping status: {response.status_code} url={url}")
    except Exception as e:
        print(f"[{now}] Self-ping failed: {e}")


class SchedulerConfig:
    SCHEDULER_API_ENABLED = False


app.config.from_object(SchedulerConfig)
scheduler.init_app(app)


@scheduler.task('interval', id='keep_render_alive', minutes=14)
def scheduled_ping():
    keep_awake()


scheduler.start()
# --- 唤醒逻辑结束 ---

app.register_blueprint(downloads_bp)
app.register_blueprint(pack_buyer_bp)
app.register_blueprint(card_sender_bp)
app.register_blueprint(deck_editor_bp)
app.register_blueprint(home_bp)
app.register_blueprint(unity_bp)
app.register_blueprint(level_editor_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(phantom_bp)

@app.route("/health")
def health():
    return {"status": "ok"}, 200


@app.route("/favicon.ico")
def favicon():
    """浏览器默认请求 /favicon.ico；占位 SVG，消除 404 日志噪音。"""
    return send_from_directory(
        app.static_folder,
        "favicon.svg",
        mimetype="image/svg+xml",
        max_age=60 * 60 * 24 * 30,
    )


@app.route("/googleb2573588fdcd8e36.html")
def google_verification():
    return app.send_static_file("googleb2573588fdcd8e36.html")


if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=False)
