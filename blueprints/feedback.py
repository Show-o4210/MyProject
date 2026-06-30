from flask import Blueprint, request, jsonify
import logging

# 假设你的 Supabase 客户端和限流器是在这两个文件中初始化的
# 如果有出入，请根据你实际的文件名修改 import 路径
from database import supabase 
from extensions import limiter 

feedback_bp = Blueprint('feedback', __name__)

# 严格限流：防止恶意灌水，同一个 IP 每小时最多提交 3 次
@feedback_bp.route('/api/feedback/submit', methods=['POST'])
@limiter.limit("3 per hour")
def submit_feedback():
    data = request.get_json()

    if not data:
        return jsonify({'error': '请求体不能为空'}), 400

    # 提取并清洗数据
    fb_type = data.get('type', 'other')
    content = data.get('content', '').strip()
    contact = data.get('contact', '').strip()

    # 1. 基础校验
    if not content:
        return jsonify({'error': '反馈内容不能为空'}), 400

    if len(content) > 500:
        return jsonify({'error': '反馈内容不能超过500字'}), 400

    if len(contact) > 100:
        return jsonify({'error': '联系方式过长'}), 400

    # 2. 收集用户环境信息（用于 Bug 排查）
    user_agent = request.headers.get('User-Agent', 'Unknown')
    # 考虑 Render 部署的代理情况，优先获取 HTTP_X_FORWARDED_FOR
    client_ip = request.headers.get('X-Forwarded-For', request.remote_addr)
    # 如果有多个 IP，取第一个真实的客户端 IP
    if client_ip and ',' in client_ip:
        client_ip = client_ip.split(',')[0].strip()

    # 3. 构建插入数据库的载荷
    # 注意：created_at 会由 Supabase 的默认值 now() 自动生成
    payload = {
        'type': fb_type,
        'content': content,
        'contact': contact,
        'ua_info': {
            'user_agent': user_agent,
            'ip': client_ip
        },
        'status': 'pending'
    }

    # 4. 写入 Supabase
    try:
        # 执行插入操作
        response = supabase.table('feedbacks').insert(payload).execute()
        return jsonify({'message': '提交成功', 'status': 'success'}), 200
        
    except Exception as e:
        # 捕获异常，避免将数据库错误直接暴露给前端
        logging.error(f"意见反馈写入数据库失败: {str(e)}")
        return jsonify({'error': '服务器开小差了，请稍后再试'}), 500