# bundle_packer.py
import UnityPy
import os
import json
import re

def clean_json_string(s):
    """【防御级数据清洗】继承自服务端的脏数据过滤"""
    if not isinstance(s, str): return s
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', s)
    cleaned = cleaned.replace('\ufeff', '').strip()
    cleaned = cleaned.replace('，', ',').replace('“', '"').replace('”', '"')
    return cleaned

def update_bundle_with_card_data(bundle_in_path, bundle_out_path, modded_card_dict, target_asset_name="cards"):
    """
    智能解析 Unity Bundle，清洗脏数据并注入修改后的卡牌 JSON，最后重新打包。
    全面修复了 TextAsset 属性丢失的底层报错。
    """
    if not os.path.exists(bundle_in_path):
        return False, f"找不到原始 Bundle 文件: {bundle_in_path}"

    try:
        env = UnityPy.load(bundle_in_path)
        modified = False
        
        for obj in env.objects:
            if obj.type.name in ["TextAsset", "MonoBehaviour"]:
                
                # ================= 核心防御策略 =================
                # 优先使用 TypeTree (字典模式)，这与你服务端的 unity.py 策略完全一致
                # 它能 100% 免疫 'TextAsset' object has no attribute 'name' 的报错
                if obj.serialized_type.nodes:
                    try:
                        tree = obj.read_typetree()
                        asset_name = tree.get("m_Name", "")
                        
                        if target_asset_name in asset_name:
                            # 智能探针：寻找数据真正存放的键值
                            target_data = None
                            data_key = None
                            
                            if "m_Script" in tree:
                                target_data = tree["m_Script"]
                                data_key = "m_Script"
                            elif "m_Text" in tree:
                                target_data = tree["m_Text"]
                                data_key = "m_Text"
                            elif "script" in tree:  # 兼容某些特殊版本的键名
                                target_data = tree["script"]
                                data_key = "script"
                            elif "1" in tree:       # 应对根目录平铺的情况
                                target_data = tree
                                data_key = "ROOT"

                            if target_data is not None:
                                is_string_json = isinstance(target_data, str)
                                is_bytes_json = isinstance(target_data, bytes)
                                
                                # 1. 解码并转为字典
                                if is_string_json:
                                    cleaned_str = clean_json_string(target_data)
                                    target_dict = json.loads(cleaned_str)
                                elif is_bytes_json:
                                    cleaned_str = clean_json_string(target_data.decode('utf-8-sig'))
                                    target_dict = json.loads(cleaned_str)
                                else:
                                    target_dict = target_data
                                    
                                # 2. 靶向注入我们修改的卡牌数据
                                for guid_str, card_data in modded_card_dict.items():
                                    target_dict[guid_str] = card_data
                                    
                                # 3. 极限压缩并还原格式
                                if is_string_json:
                                    tree[data_key] = json.dumps(target_dict, ensure_ascii=False, separators=(',', ':'))
                                elif is_bytes_json:
                                    new_str = json.dumps(target_dict, ensure_ascii=False, separators=(',', ':'))
                                    tree[data_key] = new_str.encode('utf-8')
                                else:
                                    if data_key != "ROOT":
                                        tree[data_key] = target_dict
                                        
                                # 4. 保存字典状态
                                obj.save_typetree(tree)
                                modified = True
                                break
                    except Exception as e:
                        print(f"字典解析模式跳过: {e}")

                # ================= 备用容错策略 =================
                # 如果当前对象非常古老没有 TypeTree，走原生读取，并使用 getattr 防止报错
                if not modified:
                    try:
                        data = obj.read()
                        # 【安全获取】即使没有 .name 属性也不会报错，而是返回空字符串
                        asset_name = getattr(data, 'name', getattr(data, 'm_Name', ''))
                        
                        if target_asset_name in asset_name:
                            # 安全获取文本数据
                            raw_text = getattr(data, 'script', getattr(data, 'text', getattr(data, 'm_Script', b'')))
                            is_bytes = isinstance(raw_text, bytes)
                            
                            text_str = raw_text.decode('utf-8-sig') if is_bytes else raw_text
                            cleaned_str = clean_json_string(text_str)
                            
                            target_dict = json.loads(cleaned_str)
                            for guid_str, card_data in modded_card_dict.items():
                                target_dict[guid_str] = card_data
                                
                            new_text = json.dumps(target_dict, ensure_ascii=False, separators=(',', ':'))
                            
                            # 哪里拿的塞回哪里
                            if hasattr(data, 'script'): data.script = new_text.encode('utf-8') if is_bytes else new_text
                            elif hasattr(data, 'text'): data.text = new_text.encode('utf-8') if is_bytes else new_text
                            elif hasattr(data, 'm_Script'): data.m_Script = new_text.encode('utf-8') if is_bytes else new_text
                            
                            data.save()
                            modified = True
                            break
                    except Exception as e:
                        pass # 备用方案如果也失败，静默跳过寻找下一个
                            
        if not modified:
            return False, f"在 Bundle 中未找到名为 '{target_asset_name}' 的数据节点！请确认原包是否正确。"
            
        # 确保输出文件夹存在
        os.makedirs(os.path.dirname(bundle_out_path), exist_ok=True)
        
        # 使用 LZ4 压缩重新打包 (与原游戏兼容性最好)
        with open(bundle_out_path, "wb") as f:
            f.write(env.file.save(packer="lz4"))
            
        return True, "AssetBundle 注入并打包成功！"
        
    except Exception as e:
        return False, f"打包发生严重异常: {str(e)}"

def process_bundle_in_memory(bundle_bytes, modded_card_dict, target_asset_name="cards"):
    """
    【Web专供】全内存流解包与打包方案
    接收底包的 bytes 和修改后的卡牌字典，返回打包后的新 bytes
    """
    try:
        # 直接在内存中加载 Bundle
        env = UnityPy.load(bundle_bytes)
        modified = False
        
        for obj in env.objects:
            if obj.type.name in ["TextAsset", "MonoBehaviour"]:
                # 使用 TypeTree 尝试解析
                try:
                    data = obj.read_typetree()
                    name = data.get("m_Name", "")
                    
                    if name == target_asset_name:
                        # 确定目标字段 (m_Script 或 text)
                        target_field = None
                        if "m_Script" in data: target_field = "m_Script"
                        elif "text" in data: target_field = "text"
                        elif "script" in data: target_field = "script"
                        
                        if target_field:
                            raw_str = data[target_field]
                            if isinstance(raw_str, bytes):
                                raw_str = raw_str.decode('utf-8')
                            
                            # 过滤脏数据并解析原 JSON
                            clean_str = clean_json_string(raw_str)
                            target_dict = json.loads(clean_str)
                            
                            # 将前端传来的修改覆盖进去
                            for guid_str, card_data in modded_card_dict.items():
                                target_dict[guid_str] = card_data
                                
                            # 重新转为 JSON 字符串
                            new_text = json.dumps(target_dict, ensure_ascii=False, separators=(',', ':'))
                            
                            # 写回数据
                            data[target_field] = new_text.encode('utf-8') if isinstance(data[target_field], bytes) else new_text
                            obj.save_typetree(data)
                            modified = True
                            break
                except Exception as e:
                    pass # 尝试别的对象
        
        if not modified:
            return False, "在上传的 Bundle 中未找到目标节点！", None
            
        # 在内存中使用 lz4 压缩并返回 bytes
        out_stream = env.file.save(packer="lz4")
        return True, "打包成功", out_stream
        
    except Exception as e:
        return False, f"处理失败: {str(e)}", None