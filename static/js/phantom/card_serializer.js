const NAMESPACE_ENGINE = 'PvZCards.Engine.Components.';
const ASSEMBLY_SUFFIX = ', EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null';

const SIMPLE_ABILITY_COMPONENTS = new Set(['Multishot', 'AttacksInAllLanes', 'PlaysFaceDown']);
const COUNTER_ABILITY_COMPONENTS = new Set(['Aquatic', 'Truestrike', 'Strikethrough', 'Deadly', 'Frenzy']);
const SPECIAL_COMPONENT_TO_ABILITY = {
  Multishot: 'Multishot',
  AttacksInAllLanes: 'AttacksInAllLanes',
  PlaysFaceDown: 'PlaysFaceDown',
  Aquatic: 'Aquatic',
  Truestrike: 'Truestrike',
  Strikethrough: 'Strikethrough',
  Deadly: 'Deadly',
  Frenzy: 'Frenzy',
  AttackOverride: 'AttackOverride',
  SplashDamage: 'SplashDamage',
  Armor: 'Armor',
  Untrickable: 'Untrickable',
  Teamup: 'Teamup',
  CreateInFront: 'Teamup'
};

const MANAGED_COMPONENT_NAMES = new Set([
  'Card', 'Attack', 'Health', 'SunCost', 'Plants', 'Zombies', 'Rarity',
  'Subtypes', 'Tags', 'Burst', 'Surprise', 'BoardAbility', 'Environment',
  'Superpower', 'PrimarySuperpower', 'GrantedTriggeredAbilities',
  'EffectEntitiesDescriptor', ...Object.keys(SPECIAL_COMPONENT_TO_ABILITY)
]);

function safeNumber(value, fallback = 0) {
  const num = Number(value);
  return Number.isFinite(num) ? num : fallback;
}

function ensureArray(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === 'string') {
    return value.split(/[\n,，]/).map(v => v.trim()).filter(Boolean);
  }
  return [];
}

function ensureNumberArray(value) {
  return ensureArray(value).map(v => Number(v)).filter(v => Number.isFinite(v));
}

function deepClone(value) {
  try {
    return value === undefined ? undefined : JSON.parse(JSON.stringify(value));
  } catch (_) {
    return value;
  }
}

function subtypeDisplayName(option) {
  if (!option) return '';
  const raw = String(option.raw || option.name || option.label || option.id || '').trim();
  const matched = raw.match(/\(([^()]+)\)\s*$/);
  return matched ? matched[1].trim() : raw;
}

function buildSubtypeMaps(config = {}) {
  const subtypes = config?.enums?.subtypes || [];
  const idToName = new Map();
  const nameToId = new Map();
  for (const item of subtypes) {
    const id = item.value ?? item.id;
    const displayName = subtypeDisplayName(item);
    if (id !== undefined && displayName) idToName.set(String(id), displayName);
    if (displayName && id !== undefined) nameToId.set(displayName.toLowerCase(), Number.isFinite(Number(id)) ? Number(id) : id);
  }
  return { idToName, nameToId };
}

function resolveDisplaySubtypesForOutput(values, config = {}) {
  const { idToName } = buildSubtypeMaps(config);
  return ensureArray(values).map(value => {
    const key = String(value);
    if (idToName.has(key)) return idToName.get(key);
    return Number.isFinite(Number(value)) ? Number(value) : String(value);
  }).filter(value => value !== '');
}

function resolveDisplaySubtypesForForm(values, config = {}) {
  const { nameToId } = buildSubtypeMaps(config);
  return ensureArray(values).map(value => {
    const raw = String(value).trim();
    if (nameToId.has(raw.toLowerCase())) return nameToId.get(raw.toLowerCase());
    return Number.isFinite(Number(raw)) ? Number(raw) : raw;
  }).filter(value => value !== '');
}


function normalizeComparable(value) {
  return String(value ?? '')
    .trim()
    .toLowerCase()
    .replace(/[（]/g, '(')
    .replace(/[）]/g, ')');
}

function optionDisplayName(option) {
  return String(option?.name || option?.label || option?.id || option?.value || '').trim();
}

function optionChineseName(option) {
  const name = optionDisplayName(option);
  return name.split('(')[0].trim();
}

function resolveEnumValue(value, options = [], fallback = value) {
  const raw = normalizeComparable(value);
  if (!raw) return fallback;
  const found = options.find(item => {
    const candidates = [item.id, item.value, item.name, item.label, optionChineseName(item)].map(normalizeComparable);
    return candidates.includes(raw);
  });
  return found?.value ?? found?.id ?? fallback;
}

function resolveEnumId(value, options = [], fallback = value) {
  const raw = normalizeComparable(value);
  if (!raw) return fallback;
  const found = options.find(item => {
    const candidates = [item.id, item.value, item.name, item.label, optionChineseName(item)].map(normalizeComparable);
    return candidates.includes(raw);
  });
  return found?.id ?? fallback;
}

function rarityComponentValueFromEntry(entry) {
  const comps = entry?.entity?.components || [];
  const comp = comps.find(item => parseTypeStr(item?.['$type']) === 'Rarity');
  return comp?.['$data']?.Value;
}

function buildTypeStr(componentName) {
  return `${NAMESPACE_ENGINE}${componentName}${ASSEMBLY_SUFFIX}`;
}

function parseTypeStr(typeStr) {
  if (!typeStr) return '';
  const beforeComma = String(typeStr).split(',')[0];
  const parts = beforeComma.split('.');
  return parts[parts.length - 1] || '';
}

function counterComponent(typeName, value = 0) {
  return {
    '$type': buildTypeStr(typeName),
    '$data': {
      Counters: {
        IsPersistent: true,
        Counters: [{ SourceId: -1, Duration: 0, Value: safeNumber(value, 0) }]
      }
    }
  };
}

function buildAbilityComponent(abilityKey, params = {}) {
  if (SIMPLE_ABILITY_COMPONENTS.has(abilityKey)) return [{ '$type': buildTypeStr(abilityKey), '$data': {} }];
  if (abilityKey === 'SplashDamage') return [{ '$type': buildTypeStr('SplashDamage'), '$data': { DamageAmount: safeNumber(params.SplashDamage, 1) } }];
  if (COUNTER_ABILITY_COMPONENTS.has(abilityKey)) return [counterComponent(abilityKey, 0)];
  if (abilityKey === 'AttackOverride') return [counterComponent('AttackOverride', 2)];
  if (abilityKey === 'Untrickable') return [counterComponent('Untrickable', safeNumber(params.Untrickable, 1))];
  if (abilityKey === 'Armor') return [{ '$type': buildTypeStr('Armor'), '$data': { ArmorAmount: { BaseValue: safeNumber(params.Armor, 1) } } }];
  if (abilityKey === 'Teamup') {
    const result = [counterComponent('Teamup', 0)];
    if (params.TeamupCreateInFront === true) result.push({ '$type': buildTypeStr('CreateInFront'), '$data': {} });
    return result;
  }
  return [];
}

function rarityValueFromCard(card, config) {
  const rarities = config?.enums?.rarities || [];
  const rarityId = resolveEnumId(card.rarity ?? card.rarityKey, rarities, card.rarity ?? card.rarityKey ?? '4');
  const found = rarities.find(item => String(item.id) === String(rarityId));
  return found?.value || resolveEnumValue(card.rarity, rarities, 'R0');
}

function rarityKeyFromCard(card, config) {
  const rarities = config?.enums?.rarities || [];
  const rarityId = resolveEnumId(card.rarity ?? card.rarityKey, rarities, card.rarityKey ?? card.rarity ?? 4);
  return safeNumber(rarityId, 4);
}

export function generateGameCardEntry(card, config = {}) {
  const guid = safeNumber(card.guid, 0);
  const flags = new Set(card.flags || []);
  const hasAttack = card.hasAttack !== false;
  const hasHealth = card.hasHealth !== false;
  const baseId = card.baseId || 'Base';
  const originalEntry = card.rawEntry && typeof card.rawEntry === 'object' ? card.rawEntry : null;

  if (baseId === 'BoardAbility') {
    const entities = Array.isArray(card.logicEntities) ? card.logicEntities : [];
    const components = [
      { '$type': buildTypeStr('Card'), '$data': { Guid: guid } },
      { '$type': buildTypeStr('BoardAbility'), '$data': {} },
      { '$type': buildTypeStr('SunCost'), '$data': { SunCostValue: { BaseValue: 0 } } },
      { '$type': buildTypeStr('Rarity'), '$data': { Value: 'R1' } }
    ];
    if (entities.length) components.push({ '$type': buildTypeStr('EffectEntitiesDescriptor'), '$data': { entities } });
    return {
      [String(guid)]: {
        entity: { components }, prefabName: 'BoardAbilityView', baseId: 'BasePlantOneTimeEffect', color: '0', set: 'Board', rarity: 0,
        setAndRarityKey: null, displayHealth: 0, displayAttack: 0, displaySunCost: 0, faction: 'All', ignoreDeckLimit: false,
        isPower: false, isPrimaryPower: false, isFighter: false, isEnv: false, isAquatic: false, isTeamup: false,
        subtypes: [], tags: [], subtype_affinities: [], subtype_affinity_weights: [], tag_affinities: [], tag_affinity_weights: [],
        card_affinities: [], card_affinity_weights: [], usable: true, special_abilities: []
      }
    };
  }

  const factionValue = resolveEnumValue(card.faction, config?.enums?.factions || [], card.faction || 'Plants');
  const colorValue = resolveEnumValue(card.color, config?.enums?.colors || [], card.color || 'Guardian');
  const setValue = resolveEnumValue(card.set, config?.enums?.sets || [], card.set || 'Gold');

  const components = [
    { '$type': buildTypeStr('Card'), '$data': { Guid: guid } },
    { '$type': buildTypeStr('SunCost'), '$data': { SunCostValue: { BaseValue: safeNumber(card.cost, 1) } } },
    { '$type': buildTypeStr(factionValue || 'Plants'), '$data': {} },
    { '$type': buildTypeStr('Rarity'), '$data': { Value: rarityValueFromCard(card, config) } }
  ];

  if (hasAttack) components.splice(1, 0, { '$type': buildTypeStr('Attack'), '$data': { AttackValue: { BaseValue: safeNumber(card.attack, 0) } } });
  if (hasHealth) components.splice(2, 0, { '$type': buildTypeStr('Health'), '$data': { MaxHealth: { BaseValue: safeNumber(card.health, 1) }, CurrentDamage: 0 } });

  const logicSubtypes = ensureNumberArray(card.logicSubtypes);
  const logicTags = ensureArray(card.logicTagsText || card.logicTags);
  if (logicSubtypes.length) components.push({ '$type': buildTypeStr('Subtypes'), '$data': { subtypes: logicSubtypes } });
  if (logicTags.length) components.push({ '$type': buildTypeStr('Tags'), '$data': { tags: logicTags } });

  if (flags.has('IsTrick')) components.push({ '$type': buildTypeStr('Burst'), '$data': {} });
  if (flags.has('IsSurprise')) components.push({ '$type': buildTypeStr('Surprise'), '$data': {} });
  if (flags.has('IsBoardAbility')) components.push({ '$type': buildTypeStr('BoardAbility'), '$data': {} });
  if (flags.has('IsEnvironment')) components.push({ '$type': buildTypeStr('Environment'), '$data': {} });
  if (flags.has('IsPower')) components.push({ '$type': buildTypeStr('Superpower'), '$data': {} });
  if (flags.has('IsPrimaryPower')) components.push({ '$type': buildTypeStr('PrimarySuperpower'), '$data': {} });

  const triggeredAbilities = Array.isArray(card.triggeredAbilities) && card.triggeredAbilities.length
    ? card.triggeredAbilities
    : ensureArray(card.grantedAbilities).map(normalizeGrantedAbilityToken).filter(Boolean);
  if (triggeredAbilities.length) components.push({ '$type': buildTypeStr('GrantedTriggeredAbilities'), '$data': { a: triggeredAbilities } });

  for (const abilityKey of ensureArray(card.specialAbilities)) {
    components.push(...buildAbilityComponent(abilityKey, card.abilityParams || {}));
  }

  const logicEntities = Array.isArray(card.logicEntities) ? card.logicEntities : [];
  if (logicEntities.length) components.push({ '$type': buildTypeStr('EffectEntitiesDescriptor'), '$data': { entities: logicEntities } });

  const displaySubtypes = resolveDisplaySubtypesForOutput(card.displaySubtypes, config);
  const displayTags = ensureArray(card.displayTagsText || card.displayTags);
  const preservedComponents = (originalEntry?.entity?.components || [])
    .filter(comp => !MANAGED_COMPONENT_NAMES.has(parseTypeStr(comp?.['$type'])))
    .map(comp => deepClone(comp));
  if (preservedComponents.length) components.push(...preservedComponents);
  const entityData = {
    ...(originalEntry ? deepClone(originalEntry) : {}),
    entity: { components },
    prefabName: card.prefabName || '',
    baseId,
    color: colorValue || 'Guardian',
    set: setValue || 'Gold',
    rarity: rarityKeyFromCard(card, config),
    setAndRarityKey: card.setRarityKey || '',
    craftingBuy: safeNumber(card.craftBuy, 0),
    craftingSell: safeNumber(card.craftSell, 0),
    displaySunCost: safeNumber(card.cost, 1),
    faction: factionValue || 'Plants',
    ignoreDeckLimit: flags.has('IgnoreDeckLimit'),
    isPower: flags.has('IsPower'),
    isPrimaryPower: flags.has('IsPrimaryPower'),
    isFighter: !String(baseId).includes('OneTimeEffect') && !String(baseId).includes('Environment'),
    isEnv: String(baseId).includes('Environment') || flags.has('IsEnvironment'),
    isAquatic: ensureArray(card.specialAbilities).includes('Aquatic') || Boolean(originalEntry?.isAquatic),
    isTeamup: ensureArray(card.specialAbilities).includes('Teamup') || Boolean(originalEntry?.isTeamup),
    subtypes: displaySubtypes,
    tags: displayTags,
    subtype_affinities: ensureArray(card.affinities?.subtypes),
    subtype_affinity_weights: ensureNumberArray(card.affinities?.subtypeWeights),
    tag_affinities: ensureArray(card.affinities?.tags),
    tag_affinity_weights: ensureNumberArray(card.affinities?.tagWeights),
    card_affinities: ensureNumberArray(card.affinities?.cards),
    card_affinity_weights: ensureNumberArray(card.affinities?.cardWeights),
    usable: originalEntry?.usable ?? true,
    special_abilities: ensureArray(card.rootSpecialAbilities || card.root_special_abilities)
  };
  if (hasHealth) entityData.displayHealth = safeNumber(card.health, 1);
  if (hasAttack) entityData.displayAttack = safeNumber(card.attack, 0);

  return { [String(guid)]: entityData };
}

export function generateProjectCardsJson(project, config = {}) {
  const output = {};
  for (const card of project.cards || []) {
    if (!card.guid) continue;
    Object.assign(output, generateGameCardEntry(card, config));
  }
  return output;
}

function getCounterValue(data, fallback = 1) {
  const counters = data?.Counters?.Counters;
  if (Array.isArray(counters) && counters.length) return counters[0]?.Value ?? fallback;
  return fallback;
}

function uniquePush(array, value) {
  if (value && !array.includes(value)) array.push(value);
}

function normalizeGrantedAbilityToken(token) {
  if (token && typeof token === 'object') return token;
  const raw = String(token || '').trim();
  if (!raw) return null;
  if (raw === 'DoubleStrike') return { g: 562, vt: 0, va: 0 };
  if (raw === 'Overshoot') return { g: 564, vt: 1, va: 2 };
  const numeric = Number(raw);
  if (Number.isFinite(numeric)) return { g: numeric, vt: 0, va: 0 };
  return { id: raw, note: 'Web 占位引用，建议改为真实 g/vt/va 结构' };
}

export function cardFormFromGameEntry(guid, entry, baseFactory, config = {}) {
  const card = baseFactory();
  card.guid = String(guid || '');
  card.rawEntry = deepClone(entry || {});
  card.name = entry?.name || entry?.displayName || `导入卡牌 ${guid || ''}`;
  card.prefabName = entry?.prefabName || '';
  card.baseId = entry?.baseId || 'Base';
  card.color = resolveEnumValue(entry?.color, config?.enums?.colors || [], entry?.color || 'Guardian');
  const rarityFromComponent = rarityComponentValueFromEntry(entry);
  const raritySource = entry?.rarity ?? rarityFromComponent ?? 4;
  card.rarity = String(resolveEnumId(raritySource, config?.enums?.rarities || [], raritySource));
  card.rarityKey = safeNumber(card.rarity, 4);
  card.set = resolveEnumValue(entry?.set, config?.enums?.sets || [], entry?.set || 'Gold');
  card.setRarityKey = entry?.setAndRarityKey || '';
  card.craftBuy = entry?.craftingBuy ?? 0;
  card.craftSell = entry?.craftingSell ?? 0;
  card.cost = entry?.displaySunCost ?? 1;
  card.faction = resolveEnumValue(entry?.faction, config?.enums?.factions || [], entry?.faction || 'Plants');
  card.flags = [];
  if (entry?.ignoreDeckLimit) card.flags.push('IgnoreDeckLimit');
  if (entry?.isPower) card.flags.push('IsPower');
  if (entry?.isPrimaryPower) card.flags.push('IsPrimaryPower');
  card.displaySubtypes = resolveDisplaySubtypesForForm(entry?.subtypes, config);
  card.displayTagsText = ensureArray(entry?.tags).join('\n');
  card.rootSpecialAbilities = ensureArray(entry?.special_abilities);
  card.affinities = {
    subtypes: ensureArray(entry?.subtype_affinities).join(','),
    subtypeWeights: ensureArray(entry?.subtype_affinity_weights).join(','),
    tags: ensureArray(entry?.tag_affinities).join('\n'),
    tagWeights: ensureArray(entry?.tag_affinity_weights).join(','),
    cards: ensureArray(entry?.card_affinities).join(','),
    cardWeights: ensureArray(entry?.card_affinity_weights).join(',')
  };

  card.hasAttack = false;
  card.hasHealth = false;
  card.specialAbilities = [];
  card.abilityParams = card.abilityParams || {};
  card.grantedAbilities = [];
  card.triggeredAbilities = [];
  card.logicEntities = [];

  for (const comp of entry?.entity?.components || []) {
    const name = parseTypeStr(comp?.['$type']);
    const data = comp?.['$data'] || {};
    if (name === 'Card') card.guid = String(data.Guid ?? card.guid);
    else if (name === 'Attack') { card.hasAttack = true; card.attack = data?.AttackValue?.BaseValue ?? entry?.displayAttack ?? 0; }
    else if (name === 'Health') { card.hasHealth = true; card.health = data?.MaxHealth?.BaseValue ?? entry?.displayHealth ?? 1; }
    else if (name === 'Subtypes') card.logicSubtypes = ensureNumberArray(data.subtypes);
    else if (name === 'Tags') card.logicTagsText = ensureArray(data.tags).join('\n');
    else if (name === 'EffectEntitiesDescriptor') card.logicEntities = data.entities || [];
    else if (name === 'Burst') uniquePush(card.flags, 'IsTrick');
    else if (name === 'Surprise') uniquePush(card.flags, 'IsSurprise');
    else if (name === 'Environment') uniquePush(card.flags, 'IsEnvironment');
    else if (name === 'BoardAbility') uniquePush(card.flags, 'IsBoardAbility');
    else if (name === 'Superpower') uniquePush(card.flags, 'IsPower');
    else if (name === 'PrimarySuperpower') uniquePush(card.flags, 'IsPrimaryPower');
    else if (name === 'GrantedTriggeredAbilities') {
      card.triggeredAbilities = data.a || [];
      card.grantedAbilities = (data.a || []).map(item => item.id || item.g || JSON.stringify(item));
    } else if (SPECIAL_COMPONENT_TO_ABILITY[name]) {
      const ability = SPECIAL_COMPONENT_TO_ABILITY[name];
      uniquePush(card.specialAbilities, ability);
      if (name === 'SplashDamage') card.abilityParams.SplashDamage = data.DamageAmount ?? 1;
      if (name === 'Armor') card.abilityParams.Armor = data?.ArmorAmount?.BaseValue ?? 1;
      if (name === 'Untrickable') card.abilityParams.Untrickable = getCounterValue(data, 1);
      if (name === 'CreateInFront') card.abilityParams.TeamupCreateInFront = true;
    }
  }

  if (!card.hasAttack && entry?.displayAttack !== undefined) { card.hasAttack = true; card.attack = entry.displayAttack; }
  if (!card.hasHealth && entry?.displayHealth !== undefined) { card.hasHealth = true; card.health = entry.displayHealth; }
  if (!card.logicSubtypes?.length) card.logicSubtypes = ensureNumberArray(card.displaySubtypes);
  if (!card.logicTagsText) card.logicTagsText = card.displayTagsText;
  return card;
}

export function extractEntryFromImportedJson(data, guid = '') {
  if (!data || typeof data !== 'object') throw new Error('JSON 内容不是对象');
  if (guid && data[String(guid)]) return { guid: String(guid), entry: data[String(guid)] };
  if (guid && data.entity?.components) return { guid: String(guid), entry: data };
  const keys = Object.keys(data).filter(key => data[key] && typeof data[key] === 'object');
  if (keys.length === 1) return { guid: keys[0], entry: data[keys[0]] };
  if (keys.length > 1 && !guid) throw new Error('检测到多张卡牌，请先输入要导入的 GUID');
  throw new Error(`未找到 GUID：${guid || '(空)'}`);
}
