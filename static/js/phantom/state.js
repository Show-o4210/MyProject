export const STORAGE_KEY = 'pvzh_phantom_gui_shell_v09';

export function createEmptyCard() {
  return {
    localId: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
    guid: '',
    name: '未命名卡牌',
    prefabName: '',
    faction: 'Plants',
    baseId: 'Base',
    color: 'Guardian',
    rarity: '4',
    set: 'Gold',
    setRarityKey: '',
    craftBuy: 0,
    craftSell: 0,
    cost: 1,
    attack: 0,
    health: 1,
    hasAttack: true,
    hasHealth: true,
    flags: [],
    affinities: {
      subtypes: '',
      subtypeWeights: '',
      tags: '',
      tagWeights: '',
      cards: '',
      cardWeights: ''
    },
    logicSubtypes: [],
    displaySubtypes: [],
    logicTagsText: '',
    displayTagsText: '',
    specialAbilities: [],
    abilityParams: { SplashDamage: 1, Armor: 1, Untrickable: 1, TeamupCreateInFront: false },
    rootSpecialAbilities: [],
    grantedAbilities: [],
    triggeredAbilities: [],
    logicEntities: [],
    skillTreeDraft: {
      format: 'phantom.skill_tree.v1',
      version: 1,
      roots: [],
      notes: []
    },
    skillLogicSource: ''
  };
}

export function createDefaultProject() {
  return {
    name: '未命名 Phantom 工程',
    version: '0.9-field-ability-complete',
    cards: [createEmptyCard()],
    updatedAt: new Date().toISOString()
  };
}

export const tabs = [
  { id: 'project', icon: '🏠', name: '工程大厅', desc: '工程列表与当前 Mod 卡牌清单。' },
  { id: 'basic', icon: '📋', name: '基础属性', desc: 'GUID、Prefab、阵营、稀有度、费用、攻血与 Flags。' },
  { id: 'subtypes', icon: '🧬', name: '种族配置', desc: '底层逻辑种族与 UI 显示种族。' },
  { id: 'tags', icon: '🏷️', name: '标签配置', desc: '逻辑标签与展示标签。' },
  { id: 'abilities', icon: '✨', name: '特殊能力', desc: '基础特殊能力与触发类能力列表。' },
  { id: 'logic', icon: '🧩', name: '技能逻辑', desc: 'Web 结构树编辑器、技能库、参数面板与源码兜底。' },
  { id: 'export', icon: '💾', name: '封包导出', desc: '工程校验、AB 预检、差异预览与一键注入。' },
  { id: 'preview_json', icon: '🧾', name: 'JSON 预览', desc: '独立 JSON 预览页，专门适配手机竖屏查看与复制。' },
  { id: 'theme', icon: '⚙️', name: '界面设置', desc: 'Web 版简洁样式设置壳子。' }
];

export const fallbackOptions = {
  factions: [{ id: 'Plants', value: 'Plants', name: '植物 (Plants)' }, { id: 'Zombies', value: 'Zombies', name: '僵尸 (Zombies)' }],
  baseIds: [{ id: 'Base', value: 'Base', name: '植物 (Base)' }],
  colors: [{ id: 'Guardian', value: 'Guardian', name: '守卫 (Guardian)' }],
  rarities: [{ id: '4', value: 'R0', name: '基础卡 (Common)' }],
  sets: [{ id: 'Gold', value: 'Gold', name: '高级包 (Premium/Gold)' }],
  flags: [{ id: 'IgnoreDeckLimit', value: 'IgnoreDeckLimit', name: 'IgnoreDeckLimit' }],
  subtypes: [],
  specialAbilities: [],
  rootAbilityPresets: []
};

export const emptyConfig = {
  loaded: false,
  version: 'fallback',
  stage: 'frontend-fallback',
  cardIndex: [],
  cardIndexMeta: { source: '', count: 0, loaded: false, error: '' },
  language: 'zh-CN',
  defaultFont: 'system-ui',
  supportedLanguages: ['zh-CN'],
  fonts: [],
  localization: { 'zh-CN': {} },
  skillLibrary: { total_nodes: 0, categories: [] },
  cardIndex: [],
  enums: fallbackOptions,
  notes: []
};
