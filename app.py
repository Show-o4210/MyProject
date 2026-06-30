# app.py
from flask import Flask
from extensions import limiter
from config import Config
from blueprints.unity import unity_bp
from blueprints.home import home_bp
from blueprints.deck_editor import deck_editor_bp
from flask import request
from database import supabase
from blueprints.card_sender import card_sender_bp
from blueprints.pack_buyer import pack_buyer_bp
from blueprints.downloads import downloads_bp
from blueprints.level_editor import level_editor_bp
from blueprints.feedback import feedback_bp
from flask import render_template
from blueprints.phantom import phantom_bp

# 导入新增库
import requests
import datetime
from flask_apscheduler import APScheduler

# 导入安全模块
from security import init_security_handlers

app = Flask(__name__)
app.config.from_object(Config)

limiter.init_app(app)

# 初始化安全拦截（放在蓝图注册之前）
init_security_handlers(app)

@app.route('/feedback')
def feedback_page():
    return render_template('feedback.html')

# --- 唤醒逻辑开始 ---
scheduler = APScheduler()

def keep_awake():
    """
    自唤醒任务：在北京时间 08:00 - 00:00 之间发送请求
    """
    # 强制获取北京时间 (UTC+8)
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8)))
    hour = now.hour
    
    # 设定唤醒区间：8点到24点（即次日0点前）
    if 8 <= hour < 24:
        url = "https://pvz-h-tools.onrender.com/" 
        try:
            response = requests.get(url, timeout=10)
            print(f"[{now}] Self-ping status: {response.status_code}")
        except Exception as e:
            print(f"[{now}] Self-ping failed: {e}")

# 配置调度器
class SchedulerConfig:
    SCHEDULER_API_ENABLED = False

app.config.from_object(SchedulerConfig)
scheduler.init_app(app)

# 每 14 分钟执行一次（Render 默认 15 分钟休眠）
@scheduler.task('interval', id='keep_render_alive', minutes=14)
def scheduled_ping():
    keep_awake()

# 启动调度器
scheduler.start()
# --- 唤醒逻辑结束 ---

# 注册蓝图
app.register_blueprint(downloads_bp)
app.register_blueprint(pack_buyer_bp)
app.register_blueprint(card_sender_bp)
app.register_blueprint(deck_editor_bp)
app.register_blueprint(home_bp) 
app.register_blueprint(unity_bp)
app.register_blueprint(level_editor_bp)
app.register_blueprint(feedback_bp)
app.register_blueprint(phantom_bp)

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5001))
    # 注意：在生产环境下 debug 建议设为 False
    app.run(host='0.0.0.0', port=port, debug=False)