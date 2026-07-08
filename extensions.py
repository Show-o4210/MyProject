# extensions.py
from flask import request, jsonify, render_template
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import TooManyRequests

# 初始化全局拦截器
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["1000 per day", "200 per hour"], 
    storage_uri="memory://",
    strategy="fixed-window",
)

# 方法一：通过 Flask 应用注册错误处理（需要在 app 初始化后调用）
# 或者创建一个初始化函数
def init_limiter(app):
    """在 app 中初始化限流器的错误处理"""
    limiter.init_app(app)
    
    @app.errorhandler(TooManyRequests)
    def ratelimit_handler(e):
        error_msg = f"操作太频繁啦！为了系统安全，请稍等后再试。"
        
        if request.is_json or (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html):
            return jsonify({
                "status": "error",
                "message": error_msg,
                "retry_after": e.description if hasattr(e, 'description') else 60
            }), 429
            
        return render_template('error.html', msg=error_msg), 429

import threading

# Render 免费套餐内存较小，Unity 任务统一串行执行，避免并发解包直接打爆内存。
UNITY_TASK_LOCK = threading.Lock()

def acquire_unity_lock(json_response=False):
    if UNITY_TASK_LOCK.acquire(blocking=False):
        return None

    msg = "当前已有 Unity 资源任务正在处理，请稍后再试。免费服务器内存有限，暂不支持并发解包/回填。"
    if json_response:
        return jsonify({"success": False, "error": msg}), 429
    return render_template('error.html', msg=msg), 429

def release_unity_lock():
    try:
        UNITY_TASK_LOCK.release()
    except RuntimeError:
        pass