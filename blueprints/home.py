# blueprints/home.py
import json
import os
from flask import Blueprint, render_template

home_bp = Blueprint('home', __name__)

def load_news_data():
    """读取 data/news.json 数据文件"""
    # 动态获取路径，确保在不同部署环境下都能找到文件
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, 'data', 'news.json')
    
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"读取新闻数据失败: {e}")
            
    return {"announcements": [], "changelogs": []}

@home_bp.route('/')
def index():
    # 渲染“卡片式导航大厅”并注入动态数据
    news_data = load_news_data()
    return render_template('index.html', 
                           current_tab='home', 
                           announcements=news_data.get('announcements', []),
                           changelogs=news_data.get('changelogs', []))

@home_bp.route('/tools')
def tools():
    return render_template('tab_coming_soon.html', current_tab='tools')