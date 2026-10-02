"""小型 JSON 接口的流大小限制与关卡配置预算，不影响 Bundle 上传。"""

import io
import json

from flask import jsonify, request
from werkzeug.exceptions import BadRequest, RequestEntityTooLarge


JSON_BODY_LIMITS = {
    "feedback.submit_feedback": 16 * 1024,
    "level_editor.pack_level": 128 * 1024,
    "level_editor.extract_level": 4 * 1024,
}
LEVEL_ID_MAX_LENGTH = 128
CONFIG_MAX_DEPTH = 32
CONFIG_MAX_NODES = 20_000
CONFIG_MAX_STRING_LENGTH = 4096
CONFIG_MAX_SERIALIZED_BYTES = 256 * 1024


class JsonInputError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def json_error_response(error):
    if request.endpoint == "feedback.submit_feedback":
        return jsonify({
            "ok": False, "error": str(error),
            "code": "REQUEST_TOO_LARGE" if error.status == 413 else "VALIDATION_ERROR",
        }), error.status
    return jsonify({"status": "error", "message": str(error)}), error.status


def apply_json_body_limit():
    limit = JSON_BODY_LIMITS.get(request.endpoint)
    if limit is not None:
        # Flask >= 3.1：限制实际请求流；也保留可能更小的全局限制。
        current = request.max_content_length
        request.max_content_length = min(current, limit) if current is not None else limit


def init_small_json_limits(app):
    # 必须先于安全钩子注册：安全采样也可能调用 get_json()。
    # 此处只设置流限制，保留已封禁请求的提前响应行为。
    app.before_request(apply_json_body_limit)

    @app.errorhandler(RequestEntityTooLarge)
    def body_too_large(error):
        if request.endpoint in JSON_BODY_LIMITS:
            return json_error_response(JsonInputError("请求内容过大，请缩小 JSON 后重试", 413))
        return error


def read_json_object():
    apply_json_body_limit()
    try:
        # 辅助提前拒绝；没有/不可靠的 Content-Length 仍由受限请求流检查。
        if (request.content_length is not None
                and request.content_length > request.max_content_length):
            raise RequestEntityTooLarge()
        if not request.is_json:
            raise JsonInputError("请提交 application/json 格式的请求")
        body = request.get_data()
        # LimitedStream.readall() 在 streaming 上限处可能返回截断正文，
        # 而不立刻抛 413；不要把截断后的 JSON 当作完整请求接受。
        # 终止流达到预算即拒绝（恰好等于上限也保守拒绝），不额外读原始流。
        if ("wsgi.input_terminated" in request.environ
                and len(body) >= request.max_content_length):
            raise RequestEntityTooLarge()
        data = request.get_json()
    except RequestEntityTooLarge as error:
        raise JsonInputError("请求内容过大，请缩小 JSON 后重试", 413) from error
    except BadRequest as error:
        raise JsonInputError("JSON 格式错误，请检查请求内容") from error
    except RecursionError as error:
        raise JsonInputError("JSON 嵌套过深，请简化配置", 413) from error
    if not isinstance(data, dict):
        raise JsonInputError("请求内容必须是 JSON 对象")
    return data


def validate_level_id(data):
    level_id = data.get("level_id")
    if not isinstance(level_id, str) or not level_id.strip():
        raise JsonInputError("level_id 必须是非空字符串")
    if len(level_id) > LEVEL_ID_MAX_LENGTH:
        raise JsonInputError(f"level_id 不能超过 {LEVEL_ID_MAX_LENGTH} 个字符")
    return level_id


def serialize_level_config(config):
    if not isinstance(config, dict) or not config:
        raise JsonInputError("config 必须是非空 JSON 对象")

    # 迭代器栈的空间随深度增长，避免递归或一次堆入整个宽数组。
    # 根深度为 1；对象键也计入节点数和字符串长度预算。
    stack = [(iter((config,)), 1)]
    nodes = 0
    while stack:
        children, depth = stack[-1]
        try:
            value = next(children)
        except StopIteration:
            stack.pop()
            continue
        nodes += 1
        if depth > CONFIG_MAX_DEPTH:
            raise JsonInputError(f"关卡配置嵌套不能超过 {CONFIG_MAX_DEPTH} 层", 413)
        if nodes > CONFIG_MAX_NODES:
            raise JsonInputError(f"关卡配置节点不能超过 {CONFIG_MAX_NODES} 个", 413)
        if isinstance(value, str) and len(value) > CONFIG_MAX_STRING_LENGTH:
            raise JsonInputError(f"配置中单个字符串不能超过 {CONFIG_MAX_STRING_LENGTH} 个字符", 413)
        if isinstance(value, dict):
            stack.append(((part for pair in value.items() for part in pair), depth + 1))
        elif isinstance(value, list):
            stack.append((iter(value), depth + 1))

    # 保持原有缩进格式；逐段累计 UTF-8 大小，在 Unity 操作前完成序列化。
    encoder = json.JSONEncoder(indent=4, ensure_ascii=False, allow_nan=False)
    output = io.StringIO()
    size = 0
    try:
        for chunk in encoder.iterencode(config):
            size += len(chunk.encode("utf-8"))
            if size > CONFIG_MAX_SERIALIZED_BYTES:
                raise JsonInputError("关卡配置序列化后过大，请缩小配置", 413)
            output.write(chunk)
    except (ValueError, UnicodeError) as error:
        raise JsonInputError("配置包含无效的 JSON 数值或字符") from error
    return output.getvalue()
