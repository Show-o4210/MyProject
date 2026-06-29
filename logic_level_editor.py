# logic_level_editor.py
import os
import json
import ntpath
import UnityPy

class LevelEditorLogic:
    def __init__(self):
        # 锁定项目根目录，确保 data 和 out 文件夹路径绝对安全
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(self.base_dir, "data")
        self.out_dir = os.path.join(self.base_dir, "out")
        
        self.input_ab_path = os.path.join(self.data_dir, "data_assets_36")
        self.output_ab_path = os.path.join(self.out_dir, "data_assets_36")
        
        # 确保输出目录存在
        os.makedirs(self.out_dir, exist_ok=True)

    def check_ab_exists(self):
        return os.path.exists(self.input_ab_path)

    # ================= 数据字典读取 =================
    def get_card_index(self):
        """返回卡牌索引列表 (从 data/index.json)"""
        from utils.card_index import to_level_editor_cards
        return to_level_editor_cards()

    def get_deck_db(self):
        """返回卡组列表 (从 decks.json)"""
        path = os.path.join(self.data_dir, "decks.json")
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                result = []
                for item in data:
                    form = item.get("form", "未分类")
                    cn_name = item.get("cn", "未命名")
                    deck_id = item.get("id", "")
                    if deck_id:
                        result.append({"id": deck_id, "display": f"{form} | {cn_name}"})
                return result
        except Exception as e:
            print(f"读取 decks.json 失败: {e}")
            return []

    # ================= Unity AB 包底层辅助 =================
    def _get_name(self, data_obj):
        if hasattr(data_obj, 'name') and data_obj.name: return data_obj.name
        if hasattr(data_obj, 'm_Name') and data_obj.m_Name: return data_obj.m_Name
        if hasattr(data_obj, 'container') and data_obj.container:
            return ntpath.basename(data_obj.container).split('.')[0]
        return "Unknown_TextAsset"

    def _get_text(self, data_obj):
        for attr in ['text', 'script', 'm_Script']:
            if hasattr(data_obj, attr):
                val = getattr(data_obj, attr)
                if isinstance(val, str): return val
                if isinstance(val, (bytes, bytearray)): return bytes(val).decode('utf-8', errors='ignore')
        return ""

    def _set_text(self, data_obj, new_text):
        new_bytes = new_text.encode('utf-8')
        for attr in ['text', 'script', 'm_Script']:
            if hasattr(data_obj, attr):
                if isinstance(getattr(data_obj, attr), str):
                    setattr(data_obj, attr, new_text)
                else:
                    setattr(data_obj, attr, new_bytes)
        data_obj.save()

    # ================= 核心业务逻辑 =================
    def get_all_level_ids(self):
        """获取 AB 包内所有关卡 ID"""
        if not self.check_ab_exists():
            raise FileNotFoundError("找不到 data/data_assets_36 原文件！")
        
        level_ids = []
        env = UnityPy.load(self.input_ab_path)
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                data = obj.read()
                text_content = self._get_text(data)
                if text_content and '"PlayerConfig"' in text_content and '"BoardConfig"' in text_content:
                    level_ids.append(self._get_name(data))
        return sorted(level_ids)

    def load_level_config(self, level_id):
        """根据关卡 ID 提取 JSON 配置"""
        if not self.check_ab_exists():
            raise FileNotFoundError("找不到 data/data_assets_36 原文件！")

        env = UnityPy.load(self.input_ab_path)
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                data = obj.read()
                if self._get_name(data) == level_id:
                    try:
                        return json.loads(self._get_text(data))
                    except Exception as e:
                        raise ValueError(f"解析 JSON 失败: {e}")
        raise ValueError(f"在 AB 包中未找到关卡: {level_id}")

    def pack_level_config(self, level_id, config_dict):
        """将 JSON 写入并生成新的 AB 包"""
        if not self.check_ab_exists():
            raise FileNotFoundError("找不到底包文件！")

        env = UnityPy.load(self.input_ab_path)
        found = False
        
        for obj in env.objects:
            if obj.type.name == "TextAsset":
                data = obj.read()
                if self._get_name(data) == level_id:
                    new_text = json.dumps(config_dict, indent=4, ensure_ascii=False)
                    self._set_text(data, new_text)
                    found = True
                    break
        
        if not found:
            raise ValueError(f"未在 AB 包中找到关卡 '{level_id}'！")
        
        with open(self.output_ab_path, "wb") as f:
            f.write(env.file.save())
            
        return self.output_ab_path