import logging

from flask import Blueprint, request, jsonify, render_template

from database import get_supabase
from extensions import limiter
from security import get_visitor_info

feedback_bp = Blueprint('feedback', __name__)


@feedback_bp.route('/feedback')
def feedback_page():
    return render_template('feedback.html')


@feedback_bp.route('/api/feedback/submit', methods=['POST'])
@limiter.limit("3 per hour")
def submit_feedback():
    data = request.get_json()

    if not data:
        return jsonify({'error': '请求体不能为空'}), 400

    fb_type = data.get('type', 'other')
    content = data.get('content', '').strip()
    contact = data.get('contact', '').strip()

    if not content:
        return jsonify({'error': '反馈内容不能为空'}), 400
    if len(content) > 500:
        return jsonify({'error': '反馈内容不能超过500字'}), 400
    if len(contact) > 100:
        return jsonify({'error': '联系方式过长'}), 400

    client_ip, user_agent = get_visitor_info()

    payload = {
        'type': fb_type,
        'content': content,
        'contact': contact,
        'ua_info': {
            'user_agent': user_agent,
            'ip': client_ip,
        },
        'status': 'pending',
    }

    try:
        get_supabase().table('feedbacks').insert(payload).execute()
        return jsonify({'message': '提交成功', 'status': 'success'}), 200
    except Exception as e:
        logging.error(f"意见反馈写入数据库失败: {str(e)}")
        return jsonify({'error': '服务器开小差了，请稍后再试'}), 500