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
            
        if request.endpoint == 'auth.login':
            return render_template('login.html', error=error_msg, show_register=(request.form.get('action') == 'register')), 429
            
        return render_template('error.html', message=error_msg), 429