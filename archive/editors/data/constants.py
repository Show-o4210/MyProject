# constants.py
# 英雄列表 (Hero_ID, 中文名)
# 植物英雄 (ID, 中文名)
PLANT_HEROES = [
    ("BetaCarrotina", "贝塔胡萝卜蒂娜"), ("Chomper", "霸王大嘴花"), ("Citron", "香橼猎手"),
    ("Grass_Knuckles", "拳王菜"), ("NightCap", "暗夜菇"), ("Penelopea", "绿影侠"),
    ("Rose", "玫瑰"), ("Scortchwood", "火爆队长"), ("Spudow", "土豆仔"),
    ("Sunflower", "耀斑花"), ("WallKnight", "坚果骑士")
]

# 僵尸英雄 (ID, 中文名)
ZOMBIE_HEROES = [
    ("CptBrainz", "超尸"), ("BrainFreeze", "急冻魔"), ("Cyborg", "锈铁侠"),
    ("Disco", "霹雳舞王"), ("Gargantuar", "摔跤狂"), ("HugeGigantacu", "至尊大王"),
    ("Impfinity", "无穷小子"), ("Neptuna", "海妖"), ("Professor", "僵点子教授"),
    ("Witch", "不死女妖"), ("ZMech", "Z机甲")
]

# 全英雄列表（用于搜索和兜底）
ALL_HEROES = PLANT_HEROES + ZOMBIE_HEROES

# 场景列表 (Scene_ID, 中文名)
# 场景列表 (Scene_ID, 中文名)
SCENES = [
    # ===== 正式英雄场景 =====
    ("BrainFreeze", "急冻魔冰原"),
    ("Citron", "香橼太空站"),
    ("Disco", "舞王迪斯科"),
    ("GrassKnuckles", "拳王菜海滩"),
    ("Impfinity", "无穷小子游乐园"),
    ("Neptuna", "海妖海底"),
    ("NightCap", "暗夜菇忍者屋"),
    ("Professor", "僵点子教授大学"),
    ("Rose", "玫瑰城堡"),
    ("ZMech", "Z机甲工厂"),

    # ===== 原版地图/通用地图 =====
    ("Arcade", "游戏厅"),
    ("ArenaInSpace", "太空竞技场"),
    ("Backyard", "后院"),
    ("CastlePuttPutt", "城堡高尔夫"),
    ("Greenhouse", "温室"),
    ("HauntedMansion", "鬼屋"),
    ("Junkyard", "垃圾场"),
    ("Mine", "矿洞"),
    ("ShadowFalls", "暗影瀑布"),
    ("Stadium", "体育场"),
    ("Zombopolis", "僵尸都市"),

    # ===== 教学/基础场景 =====
    ("Lawn_Plants", "植物草坪"),
    ("Lawn_Plants_tutorial", "植物教程草坪"),
    ("Lawn_Zombies", "僵尸草坪"),

    # ===== 活动/节日场景 =====
    ("Feastivus", "冬季盛典"),
    ("Luckofthezombie", "僵尸幸运节"),
    ("Springening", "春季活动"),
    ("Valenbrainz", "情尸节"),
    ("RoseRedPromo", "玫瑰红宣传图"),

    # ===== 特殊事件场景 =====
    ("CaptCombustible", "爆燃树桩"),
    ("LightTorchwood", "火炬树桩"),
    ("MeteorZ", "陨石Z")
]