# logic_unity.py
import os
import json
import UnityPy
import zipfile
from logic_data import data_manager
from utils import export_limits
import uuid

class UnityProcessor:
    def __init__(self):
        # 核心源文件：必须手动放入根目录的 data/ 文件夹下
        self.bundle_names = ["recipe_decks_1", "recipe_definitions_1"]
        self._cached_extracted_data = None

    def extract_all_to_memory(self):
        """初始化时：提取笔记中包含的卡组 JSON 供前端使用"""
        if self._cached_extracted_data is not None:
            return self._cached_extracted_data

        all_extracted_data = {}
        base_dir = os.path.dirname(os.path.abspath(__file__))
        valid_ids = data_manager.valid_eng_ids

        for b_name in self.bundle_names:
            bundle_path = os.path.join(base_dir, "data", b_name)
            if not os.path.exists(bundle_path): continue
            
            try:
                env = UnityPy.load(bundle_path)
                for obj in export_limits.iter_objects(env):
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
        self._cached_extracted_data = all_extracted_data
        return all_extracted_data

    def repack_from_server_data(self, mods_dict, output_path):
        """Only called in a disposable resource-limited worker. Fail whole exports."""
        import copy
        from utils.deck_requests import validate_mods
        from utils import export_limits
        mods_dict = validate_mods(mods_dict)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        modified = set()
        budget = export_limits.ExportBudget()
        with open(output_path, 'w+b') as output, zipfile.ZipFile(
                export_limits.BoundedOutput(output, budget, 'zip', export_limits.ZIP_MAX_BYTES, '卡组 ZIP'),
                'w', zipfile.ZIP_DEFLATED) as zf:
            for b_name in self.bundle_names:
                bundle_path = os.path.join(base_dir, 'data', b_name)
                if not os.path.isfile(bundle_path):
                    raise ValueError('找不到卡组底包')
                env = UnityPy.load(bundle_path)
                for obj in export_limits.iter_objects(env):
                    if obj.type.name != 'MonoBehaviour':
                        continue
                    tree = obj.read_typetree()
                    name = tree.get('m_Name', '')
                    if name not in mods_dict:
                        continue
                    original = tree.get('Cards', {}).get('CardEntries', [])
                    original_map = {entry.get('CardGuid'): entry for entry in original}
                    entries = []
                    for card in mods_dict[name]:
                        template = original_map.get(card['cardguid']) or (original[0] if original else None)
                        if template is None:
                            raise ValueError('底包缺少卡牌模板')
                        entry = copy.deepcopy(template)
                        entry['CardGuid'] = card['cardguid']
                        entry['NumCopies'] = card['count']
                        entry['Faction'] = card['faction']
                        if card['cardguid'] not in original_map:
                            entry['Guid'], entry['Filter'] = str(uuid.uuid4()), ''
                        entries.append(entry)
                    tree['Cards']['CardEntries'] = entries
                    obj.save_typetree(tree)
                    modified.add(name)
                saved = env.file.save(packer='lz4')
                if len(saved) > export_limits.RAW_MAX_BYTES:
                    raise export_limits.exceeded('卡组输出 Bundle 过大')
                zf.writestr(b_name, saved)
                del saved, env
        if modified != set(mods_dict):
            raise ValueError('部分卡组未匹配底包，未生成下载文件')
        return output_path

unity_processor = UnityProcessor()
