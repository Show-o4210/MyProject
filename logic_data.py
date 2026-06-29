# logic_data.py
import os
import re

from utils.card_index import to_deck_editor_cards


class DataManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DataManager, cls).__new__(cls)
            cls._instance._init_data()
        return cls._instance

    def _init_data(self):
        self.card_list = []
        self.hero_decks = {}
        self.valid_eng_ids = set()
        self.load_all_data()

    def load_all_data(self):
        base_dir = os.path.dirname(os.path.abspath(__file__))
        deck_path = os.path.join(base_dir, "data", "笔记卡组名称.txt")

        self.card_list = to_deck_editor_cards()

        if os.path.exists(deck_path):
            with open(deck_path, "r", encoding="utf-8-sig") as f:
                content = f.read()
            blocks = re.split(r'\n\s*\n', content)
            for block in blocks:
                lines = [l.strip() for l in block.split('\n') if l.strip()]
                if not lines or "【卡组ID】" in lines[0]:
                    continue

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
                            "chn_name": re.sub(r'\s+', ' ', parts[-1].strip()),
                        })


data_manager = DataManager()