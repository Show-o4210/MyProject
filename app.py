# app.py
import datetime

import requests
from flask import Flask, request
from flask_apscheduler import APScheduler

from config import Config
from extensions import init_limiter
from security import init_security_handlers
from auth_gate import init_gate_handlers
from blueprints.unity import unity_bp
from blueprints.home import home_bp
from blueprints.deck_editor import deck_editor_bp
from blueprints.card_sender import card_sender_bp
from blueprints.pack_buyer import pack_buyer_bp
from blueprints.eadp_auth import eadp_auth_bp
from blueprints.diamond_tool import diamond_tool_bp
from blueprints.downloads import downloads_bp
from blueprints.level_editor import level_editor_bp
from blueprints.feedback import feedback_bp
from blueprints.phantom import phantom_bp
from blueprints.gate import gate_bp
from blueprints.admin_tokens import admin_tokens_bp
from utils.home_tabs import resolve_home_tab

app = Flask(__name__, template_folder="templates", static_folder="static")


@app.context_processor
def inject_home_tab():
    return {'home_tab': resolve_home_tab(request.path)}


app.config.from_object(Config)

init_security_handlers(app)
init_gate_handlers(app)
init_limiter(app)

# --- 唤醒逻辑开始 ---
scheduler = APScheduler()


def keep_awake():
    """自唤醒任务：在北京时间 08:00 - 00:00 之间发送请求。"""
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    hour = now.hour

    if 8 <= hour < 24:
        url = "https://pvz-h-tools.onrender.com/"
        try:
            response = requests.get(url, timeout=10)
            print(f"[{now}] Self-ping status: {response.status_code}")
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
app.register_blueprint(eadp_auth_bp)
app.register_blueprint(diamond_tool_bp)
app.register_blueprint(pack_buyer_bp)
app.register_blueprint(card_sender_bp)
app.register_blueprint(deck_editor_bp)
app.register_blueprint(home_bp)
app.register_blueprint(unity_bp)
app.register_blueprint(level_editor_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(phantom_bp)
app.register_blueprint(gate_bp)
app.register_blueprint(admin_tokens_bp)

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5001))
    app.run(host='0.0.0.0', port=port, debug=False)