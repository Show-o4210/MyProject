# blueprints/card_sender.py
import requests
import json
import time
from flask import Blueprint, render_template, request, jsonify
from extensions import limiter

card_sender_bp = Blueprint('card_sender', __name__)

# ===================== 常量配置 =====================
CARD_API_URL = "https://pvz-heroes.awspopcap.com/persistence/v2/inventory/commitSoftPurchase"

CLIENT_ID = "pvzheroes-2015-google-client"
CLIENT_VERSION = "1.64.6"
CONTENT_VERSION = "45a337051e72592e53c9bf8a4b590639"

# 所有卡牌 ID
CARD_IDS = [
    1,2,3,4,6,8,15,18,21,24,29,31,32,33,39,43,46,49,53,54,57,58,59,61,64,65,66,70,71,76,78,79,
    80,81,82,83,84,87,88,90,91,94,95,97,98,99,101,102,103,104,105,106,108,109,110,111,115,116,
    117,118,119,120,122,123,124,125,126,127,128,129,130,132,134,138,139,140,141,142,143,145,148,150,
    151,152,153,154,156,157,158,159,160,161,163,164,165,167,169,170,171,174,175,176,178,180,181,182,
    186,187,190,191,193,194,195,196,197,198,199,201,202,203,204,206,207,209,213,214,215,216,217,
    218,220,221,222,225,226,227,228,230,231,234,235,237,238,240,241,242,243,247,248,249,251,252,253,
    255,256,257,281,282,284,285,286,293,294,296,297,298,299,300,304,306,307,308,309,310,312,313,314,
    315,316,317,322,323,324,327,328,330,332,333,334,339,340,342,344,346,353,398,399,401,402,403,404,
    405,406,407,408,409,410,411,413,414,415,416,417,418,419,420,421,422,423,424,425,426,427,428,429,
    430,431,432,433,434,435,436,437,438,439,440,441,442,443,444,445,446,447,448,449,450,451,452,453,
    454,455,456,457,458,459,461,462,463,464,465,466,467,468,469,470,471,472,473,474,476,477,478,479,
    480,481,482,483,484,485,486,487,488,489,490,491,492,493,494,495,496,497,498,499,
    500,501,502,503,504,505,506,507,508,510,511,512,513,514,515,516,517,518,519,520,521,524,525,526,
    527,528,529,530,531,532,533,534,535,536,537,538,539,540,541,542,543,544,545,546,547,548,549,550,
    551,552,553,554,555,556,557,558,560,566,568,569,585,586,587,588,589,591,594,595,596,597,598,599,
    600,601,602,603,604,605,606,607,608,609,610,611,612,613,614,616,617,618,619,620,621,622,623,624,
    625,626,627,628,629,630,631,632,633,634,635,636,637,638,639,640,641,642,643,645,646,647,648,649,
    650,651,653,655,656,657,658,659,660,661,662,663,664,665,666,667,669,670,671,672,673,674,675,676,
    677,678,679,680,681,682,683,684,685,686,687,688,691
]

def build_cards(count: int) -> dict:
    """构建卡牌字典"""
    return {str(cid): count for cid in CARD_IDS}

@card_sender_bp.route('/card-sender')
def card_sender_page():
    """渲染卡牌发送器页面"""
    return render_template('card_sender.html', current_tab='card_sender', card_ids_count=len(CARD_IDS))

@card_sender_bp.route('/api/send-cards', methods=['POST'])
@limiter.limit("5 per minute")
def send_cards():
    """
    发送卡牌请求
    无需登录，直接使用前端传入的 Token 和 Persona ID
    """
    # 获取请求参数
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "无效的请求数据"}), 400
    
    eadp_token = data.get('token', '').strip()
    persona_id = data.get('persona_id', '').strip()
    card_count = data.get('card_count', 999999)
    
    # 参数校验
    if not eadp_token:
        return jsonify({"success": False, "error": "EADP-AUTH-TOKEN 不能为空"}), 400
    
    if not persona_id:
        return jsonify({"success": False, "error": "EADP-PERSONA-ID 不能为空"}), 400
    
    try:
        card_count = int(card_count)
        if card_count <= 0:
            return jsonify({"success": False, "error": "卡牌数量必须大于 0"}), 400
        if card_count > 999999:
            return jsonify({"success": False, "error": "每张卡牌数量不能超过 999999"}), 400
    except ValueError:
        return jsonify({"success": False, "error": "卡牌数量必须是有效的数字"}), 400
    
    # 生成 UTC 时间戳
    utc = str(int(time.time() * 1000))
    
    # 构建请求
    payload = {
        "Sku": "deckRecipe",
        "EventId": None,
        "Cards": build_cards(card_count),
        "ExpectedCost": 10,
        "KeyName": "default"
    }
    
    headers = {
        "Content-Type": "application/json",
        "EADP-AUTH-TOKEN": eadp_token,
        "EADP-PERSONA-ID": persona_id,
        "X-EADP-Client-Id": CLIENT_ID,
        "X-Pvzh-UTC": utc,
        "X-Pvzh-Platform": "Android",
        "X-Pvzh-Content-Version": CONTENT_VERSION,
        "X-Pvzh-Client-Version": CLIENT_VERSION
    }
    
    # 发送请求
    try:
        response = requests.post(
            CARD_API_URL, 
            json=payload, 
            headers=headers, 
            timeout=10
        )
        
        # 尝试解析响应
        response_text = response.text
        response_json = None
        try:
            response_json = json.loads(response_text)
        except:
            pass
        
        return jsonify({
            "success": response.status_code == 200,
            "status_code": response.status_code,
            "response": response_json if response_json else response_text,
            "total_cards": len(CARD_IDS) * card_count
        })
        
    except requests.Timeout:
        return jsonify({"success": False, "error": "请求超时，请稍后重试"}), 504
    except requests.ConnectionError:
        return jsonify({"success": False, "error": "网络连接失败"}), 503
    except Exception as e:
        return jsonify({"success": False, "error": f"请求失败: {str(e)}"}), 500