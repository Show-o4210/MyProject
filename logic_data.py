# logic_data.py
import os
import re

class DataManager:
    _instance = None

    # 单例模式：确保全局只加载一次数据
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataManager, cls).__new__(cls)
            cls._instance._init_data()
        return cls._instance

    def _init_data(self):
        self.card_list = []      # 给前端用的扁平化卡牌列表
        self.hero_decks = {}     # 给前端用的卡组树
        self.valid_eng_ids = set() 
        
        # 强制在初始化时加载
        self.load_all_data()

    def load_all_data(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        uuid_path = os.path.join(base_dir, "data", "uuid.txt")
        deck_path = os.path.join(base_dir, "data", "笔记卡组名称.txt")

        # 1. 加载 UUID
        if os.path.exists(uuid_path):
            # 保持 utf-8-sig 应对 Windows 记事本可能带来的 BOM 头
            with open(uuid_path, "r", encoding="utf-8-sig") as f:
                for line in f:
                    # 剔除零宽字符及首尾空白
                    line = line.strip().replace('\u200b', '')
                    
                    # 如果是空行或者没有你指定的标准分隔符，直接跳过
                    if not line or "——————" not in line: 
                        continue
                    
                    # 核心修改：直接暴力切片，抛弃正则
                    parts = line.split("——————")
                    
                    # 确保切出来至少有 3 块 (序号, UUID, 卡牌名)
                    if len(parts) >= 3:
                        try:
                            # 分别提取并清除周围可能存在的 Tab 或空格
                            c_id = int(parts[0].strip())
                            clean_uuid = parts[1].strip()
                            raw_name = parts[2].strip()
                            
                            # 清理卡牌名称内部多余的连续空格（比如把"豌豆  射手"变成"豌豆 射手"）
                            clean_name = re.sub(r'\s+', ' ', raw_name)
                            
                            # 简单的阵营判断
                            zombie_keywords = ["僵尸", "急冻魔", "霹雳舞王", "不死女妖", "无穷小子", "海妖", "教授", "锈铁侠", "超尸", "摔跤狂", "Z机甲", "错误"]
                            faction = 1 if any(kw in clean_name for kw in zombie_keywords) else 0

                            self.card_list.append({
                                "name": clean_name,
                                "CardGuid": c_id,
                                "Guid": clean_uuid,
                                "Faction": faction
                            })
                        except ValueError as e:
                            # 容错：如果序号转数字失败，打印出来方便排查
                            print(f"解析异常(数据跳过): {line} -> 错误信息: {e}")
                            continue

        # 2. 加载卡组名称 (保持上一版的读取逻辑)
        if os.path.exists(deck_path):
            with open(deck_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
            blocks = re.split(r'\n\s*\n', content)
            for block in blocks:
                lines = [l.strip() for l in block.split('\n') if l.strip()]
                if not lines or "【卡组ID】" in lines[0]: continue
                
                first_name = lines[0].split('\t')[-1]
                hero_name = re.sub(r'\(.*?\)', '', first_name).strip()
                if hero_name not in self.hero_decks:
                    self.hero_decks[hero_name] = []
                
                for line in lines:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        eng_id = parts[0].strip()
                        self.valid_eng_ids.add(eng_id)
                        self.hero_decks[hero_name].append({
                            "eng_id": eng_id,
                            "chn_name": re.sub(r'\s+', ' ', parts[-1].strip())
                        })  

# 实例化给其他文件导入使用
data_manager = DataManager()