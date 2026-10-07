export const STORAGE_KEY = 'pvzh_phantom_single_card_v1';

export function labelOf(item) {
  if (!item) return '';
  return item.name || item.label || item.value || item.id || '';
}

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
      format: 'phantom.skill_tree.v3',
      version: 3,
      roots: [],
      notes: []
    }
  };
}

export const tabs = [
  { id: 'basic', icon: '📋', name: '基础属性', desc: '导入 JSON、GUID、阵营、费用、攻血与核心标记。', shortName: '属性' },
  { id: 'traits', icon: '🧬', name: '种族标签', desc: '底层种族与逻辑 / 展示标签。', shortName: '标签' },
  { id: 'abilities', icon: '✨', name: '特殊能力', desc: '组件能力与触发类技能。', shortName: '能力' },
  { id: 'logic', icon: '⚡', name: '技能逻辑', desc: '结构树编辑技能，自动同步到 JSON。', shortName: '技能' },
  { id: 'json', icon: '📄', name: 'JSON 输出', desc: '预览、复制与下载单卡 JSON。', shortName: 'JSON' }
];

export const logicWorkspaceTabs = [
  { id: 'library', icon: '📚', name: '组件库', shortName: '组件' },
  { id: 'tree', icon: '🌳', name: '工作区', shortName: '工作区' },
  { id: 'inspector', icon: '🛠️', name: '检查器', shortName: '检查' },
  { id: 'json', icon: '📋', name: '技能 JSON', shortName: 'JSON' }
];

export const fallbackOptions = {
  factions: [
    { id: 'Plants', value: 'Plants', name: '植物 (Plants)' },
    { id: 'Zombies', value: 'Zombies', name: '僵尸 (Zombies)' }
  ],
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
  stage: 'json-creator',
  cardIndex: [],
  cardIndexMeta: { source: '', count: 0, loaded: false, error: '' },
  nodeDef: {},
  localization: { node_names: {}, param_names: {}, enum_names: {} },
  palette: [],
  userPresets: {},
  skillLibrary: { total_nodes: 0, categories: [] },
  enums: fallbackOptions
};