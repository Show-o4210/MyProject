# extensions.py
import threading
import time

from flask import request, jsonify, render_template
from flask_limiter import Limiter
from werkzeug.exceptions import TooManyRequests

from security import visitor_ip_key

# 初始化全局拦截器
# 必须用 visitor_ip_key：Render/反代后 remote_addr 几乎都是 127.0.0.1，
# 若用 get_remote_address 会导致全站共用一个限流桶，正常用户误触 429。
limiter = Limiter(
    key_func=visitor_ip_key,
    default_limits=["2000 per day", "400 per hour"],
    storage_uri="memory://",
    strategy="fixed-window",
)

# Unity 任务锁：忙时短暂排队，避免用户连点/预检刚结束立刻回填时直接 429。
# 最长等待秒数（免费机内存仍只允许真正并发 1 个 Unity 任务）。
UNITY_LOCK_WAIT_SECONDS = 25


def init_limiter(app):
    """在 app 中初始化限流器的错误处理，并豁免健康检查等路径。"""
    limiter.init_app(app)

    # 健康检查不计入默认限流
    try:
        health_view = app.view_functions.get("health")
        if health_view is not None:
            limiter.exempt(health_view)
    except Exception:
        pass

    @app.errorhandler(TooManyRequests)
    def ratelimit_handler(e):
        error_msg = "操作太频繁啦！为了系统安全，请稍等后再试。"

        if _wants_json_error():
            return jsonify({
                "ok": False,
                "success": False,
                "error": error_msg,
                "status": "error",
                "message": error_msg,
                "code": "RATE_LIMITED",
                "retry_after": e.description if hasattr(e, "description") else 60,
            }), 429

        return render_template("error.html", msg=error_msg), 429


# Render 免费套餐内存较小，Unity 任务统一串行执行，避免并发解包直接打爆内存。
UNITY_TASK_LOCK = threading.Lock()


def _wants_json_error():
    """fetch / XHR 客户端优先返回 JSON 错误，避免整页 document.write。"""
    if request.is_json:
        return True
    if request.headers.get("X-Requested-With") in {"XMLHttpRequest", "fetch"}:
        return True
    # Accept 明确偏好 JSON，且未更偏好 HTML
    best = request.accept_mimetypes.best
    if best == "application/json":
        return True
    if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
        return True
    return False


def unity_busy_response(json_response=False):
    msg = (
        "当前已有 Unity 资源任务正在处理，请稍后再试。"
        "免费服务器内存有限，暂不支持并发解包/回填。"
    )
    if json_response or _wants_json_error():
        return jsonify({"success": False, "error": msg, "code": "UNITY_BUSY"}), 429
    return render_template("error.html", msg=msg), 429


def acquire_unity_lock(json_response=False, wait_seconds=None):
    """
    获取全局 Unity 任务锁。

    - 先非阻塞尝试；失败则在 wait_seconds 内短排队（覆盖连点/预检→回填竞态）。
    - 仍拿不到则 429，不长时间占着 worker 干等。
    """
    if wait_seconds is None:
        wait_seconds = UNITY_LOCK_WAIT_SECONDS

    if UNITY_TASK_LOCK.acquire(blocking=False):
        return None

    deadline = time.time() + max(0, float(wait_seconds))
    while time.time() < deadline:
        if UNITY_TASK_LOCK.acquire(blocking=False):
            return None
        time.sleep(0.35)

    return unity_busy_response(json_response=json_response)


def release_unity_lock():
    try:
        UNITY_TASK_LOCK.release()
    except RuntimeError:
        pass
