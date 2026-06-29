# logic_unity.py
import os
import json
import UnityPy
from io import BytesIO
import zipfile
from logic_data import data_manager
import uuid

class UnityProcessor:
    def __init__(self):
        # 核心源文件：必须手动放入根目录的 data/ 文件夹下
        self.bundle_names = ["recipe_decks_1", "recipe_definitions_1"]

    def extract_all_to_memory(self):
        """初始化时：提取笔记中包含的卡组 JSON 供前端使用"""
        all_extracted_data = {}
        base_dir = os.path.dirname(os.path.abspath(__file__))
        valid_ids = data_manager.valid_eng_ids

        for b_name in self.bundle_names:
            bundle_path = os.path.join(base_dir, "data", b_name)
            if not os.path.exists(bundle_path): continue
            
            try:
                env = UnityPy.load(bundle_path)
                for obj in env.objects:
                    if obj.type.name == "MonoBehaviour":
                        try:
                            tree = obj.read_typetree()
                            name_val = tree.get("m_Name", "")
                            for eng_id in valid_ids:
                                if eng_id in name_val:
                                    all_extracted_data[eng_id] = tree
                                    break
                        except: continue
            except Exception as e:
                print(f"解析 {b_name} 失败: {e}")
        return all_extracted_data

    def repack_from_server_data(self, mods_dict):
        """[编辑器专属] 利用服务器底包在内存中回填，实现一键打包"""
        memory_zip = BytesIO()
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        with zipfile.ZipFile(memory_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
            for b_name in self.bundle_names:
                bundle_path = os.path.join(base_dir, "data", b_name)
                if not os.path.exists(bundle_path):
                    print(f"警告: 找不到文件 {bundle_path}")
                    continue
                
                try:
                    env = UnityPy.load(bundle_path)
                    
                    for obj in env.objects:
                        if obj.type.name == "MonoBehaviour":
                            try:
                                tree = obj.read_typetree()
                                m_name = tree.get("m_Name", "")
                                
                                if m_name in mods_dict:
                                    print(f"正在修改卡组: {m_name}")
                                    
                                    # 获取原始卡牌条目
                                    original_entries = tree.get("Cards", {}).get("CardEntries", [])
                                    
                                    # 创建原始卡牌的映射表
                                    original_map = {}
                                    for entry in original_entries:
                                        card_guid = entry.get("CardGuid")
                                        if card_guid is not None:
                                            original_map[card_guid] = entry
                                    
                                    # 构建新的 CardEntries
                                    new_entries = []
                                    for card_data in mods_dict[m_name]:
                                        card_guid = card_data['cardguid']
                                        
                                        # 确保 CardGuid 是整数
                                        if not isinstance(card_guid, int):
                                            card_guid = int(card_guid)
                                        
                                        # 查找或创建条目
                                        if card_guid in original_map:
                                            # ✅ 使用原始条目的完全拷贝
                                            import copy
                                            new_entry = copy.deepcopy(original_map[card_guid])
                                            # ✅ 只修改数量，保持其他所有字段不变
                                            new_entry["NumCopies"] = int(card_data.get('count', 1))
                                        else:
                                            # 新卡牌：使用模板（第一条记录）
                                            if original_entries:
                                                import copy
                                                new_entry = copy.deepcopy(original_entries[0])
                                                # 设置新卡牌的值
                                                new_entry["CardGuid"] = card_guid
                                                new_entry["NumCopies"] = int(card_data.get('count', 1))
                                                # ✅ Faction 必须是整数
                                                faction_val = card_data.get('faction', 0)
                                                if isinstance(faction_val, int):
                                                    new_entry["Faction"] = faction_val
                                                else:
                                                    # 如果是字符串，转换为整数
                                                    new_entry["Faction"] = 1 if faction_val == "Zombie" else 0
                                                new_entry["Guid"] = str(uuid.uuid4())
                                                new_entry["Filter"] = ""
                                            else:
                                                print(f"警告: 卡组 {m_name} 没有原始卡牌，跳过")
                                                continue
                                        
                                        new_entries.append(new_entry)
                                    
                                    # 更新 tree
                                    tree["Cards"]["CardEntries"] = new_entries
                                    
                                    # 保存
                                    obj.save_typetree(tree)
                                    print(f"成功修改卡组: {m_name}, 共 {len(new_entries)} 张卡牌")
                                    
                            except Exception as e:
                                print(f"处理对象时出错: {e}")
                                import traceback
                                traceback.print_exc()
                                continue
                    
                    # 保存 bundle
                    zf.writestr(b_name, env.file.save(packer="lz4"))
                    print(f"已写入: {b_name}")
                        
                except Exception as e:
                    print(f"加载bundle {b_name} 失败: {e}")
                    continue
        
        memory_zip.seek(0)
        return memory_zip

unity_processor = UnityProcessor()