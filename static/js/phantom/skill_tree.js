export const SKILL_TREE_FORMAT = 'phantom.skill_tree.v2';

function makeUid(prefix = 'node') {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}

function cloneJson(value, fallback = {}) {
  try {
    if (value === undefined || value === null) return fallback;
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

function isPlainObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value);
}

function isTypedObject(value) {
  return isPlainObject(value) && (value.$type || value.type || value.Type);
}

function isRealEntity(value) {
  return isPlainObject(value) && Array.isArray(value.components) && !value.$type;
}

function shortType(type = '') {
  const text = String(type || '');
  if (!text) return '';
  const beforeComma = text.split(',')[0];
  const parts = beforeComma.split('.');
  return parts[parts.length - 1] || text;
}

function typeNamespace(type = '') {
  const text = String(type || '');
  if (text.includes('.Queries.')) return 'Query';
  if (text.includes('.Components.')) return 'Component';
  return 'Object';
}

function buildFullType(node) {
  if (node?.full_type) return node.full_type;
  if (node?.type && String(node.type).startsWith('PvZCards.')) return node.type;
  const ns = node?.namespace_hint || (node?.category === 'Query' || node?.category === 'CompositeQuery' ? 'Queries' : 'Components');
  return `PvZCards.Engine.${ns}.${node?.node_id || node?.id || 'Unknown'}, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null`;
}

export function buildSkillLibraryIndex(skillLibrary = {}) {
  const byId = {};
  const byTypeName = {};
  const byFullType = {};
  for (const category of skillLibrary?.categories || []) {
    for (const node of category.nodes || []) {
      const normalized = { ...node, category: node.category || category.id };
      byId[node.id] = normalized;
      byTypeName[shortType(node.type || node.id)] = normalized;
      if (node.type) byFullType[node.type] = normalized;
    }
  }
  return { byId, byTypeName, byFullType };
}

function inferParamMetaFromValue(value) {
  if (typeof value === 'boolean') return { type: 'bool' };
  if (typeof value === 'number') return { type: Number.isInteger(value) ? 'int' : 'float' };
  if (typeof value === 'string') return { type: 'string' };
  return { type: 'json' };
}

function inferEditableParams(params = {}) {
  const meta = {};
  for (const [key, value] of Object.entries(params || {})) {
    if (value === null || value === undefined) meta[key] = { type: 'json' };
    else if (Array.isArray(value) || isPlainObject(value)) meta[key] = { type: 'json' };
    else meta[key] = inferParamMetaFromValue(value);
  }
  return meta;
}

export function normalizeSkillTreeDraft(input = {}) {
  const roots = Array.isArray(input?.roots) ? input.roots : [];
  return {
    format: input?.format || SKILL_TREE_FORMAT,
    version: input?.version || 2,
    roots: roots.map(normalizeTreeNode),
    notes: input?.notes || []
  };
}

export function normalizeTreeNode(node = {}) {
  const params = cloneJson(node.params ?? node.default_data, {});
  const editable = Object.keys(node.editable_params || {}).length ? cloneJson(node.editable_params, {}) : inferEditableParams(params);
  return {
    uid: node.uid || makeUid('tree'),
    node_id: node.node_id || node.id || node.name || 'UnknownNode',
    name: node.name || node.node_id || node.id || 'UnknownNode',
    type: node.type || node.category || 'Unknown',
    full_type: node.full_type || (String(node.type || '').startsWith('PvZCards.') ? node.type : null),
    category: node.category || node.type || 'Unknown',
    real_kind: node.real_kind || null,
    relation: cloneJson(node.relation || null, null),
    namespace_hint: node.namespace_hint || null,
    params,
    editable_params: editable,
    allowed_children: Array.isArray(node.allowed_children) ? [...node.allowed_children] : [],
    child_prop: node.child_prop ?? null,
    is_list: node.is_list === true,
    disabled: node.disabled === true,
    collapsed: node.collapsed === true,
    raw: node.raw !== undefined ? cloneJson(node.raw, node.raw) : null,
    children: Array.isArray(node.children) ? node.children.map(normalizeTreeNode) : []
  };
}

export function createTreeNodeFromLibraryNode(node = {}) {
  return normalizeTreeNode({
    uid: makeUid('tree'),
    node_id: node.id || node.node_id || 'UnknownNode',
    name: node.name || node.id || 'UnknownNode',
    type: node.type || node.category || 'Unknown',
    full_type: node.type || null,
    category: node.category || node.type || 'Unknown',
    namespace_hint: node.category === 'Query' || node.category === 'CompositeQuery' ? 'Queries' : 'Components',
    params: cloneJson(node.default_data, {}),
    editable_params: cloneJson(node.editable_params, {}),
    allowed_children: Array.isArray(node.allowed_children) ? [...node.allowed_children] : [],
    child_prop: node.child_prop ?? null,
    is_list: node.is_list === true,
    disabled: false,
    children: []
  });
}

export function findNodeAndParent(roots = [], uid) {
  if (!uid) return { node: null, parent: null, list: roots, index: -1 };
  const walk = (list, parent = null) => {
    for (let index = 0; index < list.length; index += 1) {
      const node = list[index];
      if (node.uid === uid) return { node, parent, list, index };
      const found = walk(node.children || [], node);
      if (found.node) return found;
    }
    return { node: null, parent: null, list: roots, index: -1 };
  };
  return walk(roots, null);
}

export function flattenSkillTree(roots = []) {
  const rows = [];
  const walk = (nodes, depth = 0, parentUid = null) => {
    for (const node of nodes || []) {
      rows.push({ node, depth, parentUid, hasChildren: !!(node.children && node.children.length) });
      if (!node.collapsed) walk(node.children || [], depth + 1, node.uid);
    }
  };
  walk(roots, 0, null);
  return rows;
}

export function addChildNode(roots, parentUid, newNode) {
  if (!parentUid) {
    roots.push(newNode);
    return newNode;
  }
  const { node } = findNodeAndParent(roots, parentUid);
  if (!node) {
    roots.push(newNode);
    return newNode;
  }
  node.children = Array.isArray(node.children) ? node.children : [];
  node.children.push(newNode);
  node.collapsed = false;
  return newNode;
}

export function removeTreeNode(roots, uid) {
  const found = findNodeAndParent(roots, uid);
  if (!found.node || found.index < 0) return false;
  found.list.splice(found.index, 1);
  return true;
}

export function moveTreeNode(roots, uid, direction) {
  const found = findNodeAndParent(roots, uid);
  if (!found.node || found.index < 0) return false;
  const next = found.index + direction;
  if (next < 0 || next >= found.list.length) return false;
  const [item] = found.list.splice(found.index, 1);
  found.list.splice(next, 0, item);
  return true;
}

export function cloneTreeNode(node) {
  const cloned = normalizeTreeNode(cloneJson(node, {}));
  const refresh = (n) => {
    n.uid = makeUid('tree');
    (n.children || []).forEach(refresh);
  };
  refresh(cloned);
  cloned.name = `${cloned.name} 副本`;
  return cloned;
}

export function duplicateTreeNode(roots, uid) {
  const found = findNodeAndParent(roots, uid);
  if (!found.node || found.index < 0) return null;
  const cloned = cloneTreeNode(found.node);
  found.list.splice(found.index + 1, 0, cloned);
  return cloned;
}

export function treeNodeSummary(node) {
  const params = node?.params || {};
  const keys = Object.keys(params);
  const childCount = node?.children?.length || 0;
  const pieces = [];
  if (node?.relation?.key) pieces.push(`来自 ${node.relation.key}${node.relation.mode === 'array' ? '[]' : ''}`);
  if (keys.length) pieces.push(keys.slice(0, 3).map(k => `${k}: ${JSON.stringify(params[k])}`).join('，'));
  if (childCount) pieces.push(`${childCount} 个子节点`);
  if (node?.disabled) pieces.push('已禁用');
  return pieces.join(' · ') || '无参数';
}

function splitDataToParamsAndChildren(data = {}, relationBase = {}) {
  const params = {};
  const childSpecs = [];

  for (const [key, value] of Object.entries(data || {})) {
    if (isTypedObject(value)) {
      childSpecs.push({ value, relation: { ...relationBase, key, mode: 'single' } });
    } else if (Array.isArray(value) && value.some(isTypedObject)) {
      value.forEach((item, index) => {
        if (isTypedObject(item)) childSpecs.push({ value: item, relation: { ...relationBase, key, mode: 'array', index } });
      });
      const nonTypedItems = value.filter(item => !isTypedObject(item));
      if (nonTypedItems.length) params[key] = nonTypedItems;
    } else {
      params[key] = cloneJson(value, value);
    }
  }
  return { params, childSpecs };
}

function readableNodeName(nodeId, fullType, libraryIndex = {}) {
  const found = libraryIndex.byFullType?.[fullType] || libraryIndex.byTypeName?.[nodeId] || libraryIndex.byId?.[nodeId];
  return found?.name || nodeId;
}

function nodeMetaFromLibrary(nodeId, fullType, libraryIndex = {}) {
  return libraryIndex.byFullType?.[fullType] || libraryIndex.byTypeName?.[nodeId] || libraryIndex.byId?.[nodeId] || null;
}

function componentCategory(nodeId, fullType) {
  if (fullType?.includes('.Queries.')) return nodeId.includes('Composite') ? 'CompositeQuery' : 'Query';
  if (nodeId.endsWith('Trigger')) return 'Trigger';
  if (nodeId.endsWith('Filter')) return 'Filter';
  if (nodeId.endsWith('EffectDescriptor') || nodeId.endsWith('Effect')) return 'Effect';
  if (nodeId.endsWith('Query')) return nodeId.includes('Composite') ? 'CompositeQuery' : 'Query';
  return typeNamespace(fullType);
}

function realObjectToNode(object, relation = null, libraryIndex = {}) {
  const fullType = object?.$type || object?.type || object?.Type || '';
  const nodeId = shortType(fullType) || object?.id || object?.name || 'LogicObject';
  const data = cloneJson(object?.$data || object?.data || object?.Data || {}, {});
  const { params, childSpecs } = splitDataToParamsAndChildren(data, relation || {});
  const meta = nodeMetaFromLibrary(nodeId, fullType, libraryIndex);
  const children = childSpecs.map(spec => realObjectToNode(spec.value, spec.relation, libraryIndex));
  return normalizeTreeNode({
    uid: makeUid('real'),
    node_id: nodeId,
    name: readableNodeName(nodeId, fullType, libraryIndex),
    type: fullType || nodeId,
    full_type: fullType || null,
    category: meta?.category || componentCategory(nodeId, fullType),
    real_kind: 'typed_object',
    relation,
    namespace_hint: fullType.includes('.Queries.') ? 'Queries' : 'Components',
    params,
    editable_params: meta?.editable_params || inferEditableParams(params),
    allowed_children: meta?.allowed_children || [],
    child_prop: meta?.child_prop ?? null,
    is_list: meta?.is_list === true,
    raw: object,
    children
  });
}

function realEntityToNode(entity, index = 0, libraryIndex = {}) {
  return normalizeTreeNode({
    uid: makeUid('entity'),
    node_id: `EffectEntity_${index + 1}`,
    name: `技能实体 #${index + 1}`,
    type: 'EffectEntity',
    category: 'Entity',
    real_kind: 'entity',
    params: {},
    editable_params: {},
    raw: entity,
    children: (entity?.components || []).map((component, componentIndex) => realObjectToNode(component, { key: 'components', mode: 'array', index: componentIndex }, libraryIndex))
  });
}

export function buildTreeFromRealLogicEntities(entities = [], skillLibrary = {}) {
  const libraryIndex = buildSkillLibraryIndex(skillLibrary);
  return normalizeSkillTreeDraft({
    format: SKILL_TREE_FORMAT,
    notes: ['由 EffectEntitiesDescriptor.entities 读取生成。v1.1 起会把 entity.components、Query、queries[] 等嵌套结构展开为可读树。'],
    roots: (Array.isArray(entities) ? entities : []).map((entity, index) => realEntityToNode(entity, index, libraryIndex))
  });
}

function insertChildIntoData(data, child) {
  const relation = child.relation || {};
  const key = relation.key || child.child_prop || 'children';
  const object = treeNodeToRealObject(child);
  if (relation.mode === 'array' || child.is_list) {
    if (!Array.isArray(data[key])) data[key] = [];
    data[key].push(object);
  } else {
    data[key] = object;
  }
}

function treeNodeToRealObject(node) {
  const fullType = buildFullType(node);
  const data = cloneJson(node.params || {}, {});
  for (const child of node.children || []) insertChildIntoData(data, child);
  return { '$type': fullType, '$data': data };
}

export function buildRealLogicEntitiesFromTreeDraft(draft = {}) {
  const normalized = normalizeSkillTreeDraft(draft);
  if (!normalized.roots.length) return [];
  const entityRoots = normalized.roots.filter(root => root.real_kind === 'entity' || root.category === 'Entity');
  if (entityRoots.length) {
    return entityRoots.map(root => ({ components: (root.children || []).map(treeNodeToRealObject) }));
  }
  return [{ components: normalized.roots.map(treeNodeToRealObject) }];
}

export function buildSkillTreeSource(draft = {}) {
  return {
    format: SKILL_TREE_FORMAT,
    version: 2,
    warning: '这是 Phantom Web 结构树草稿。v1.1 已支持把真实 logicEntities 读取为树，并可显式转换回 EffectEntitiesDescriptor.entities。写回前请检查源码。',
    roots: normalizeSkillTreeDraft(draft).roots
  };
}


// v1.2: quick skill templates for low-threshold editing.
function T(namespace, name) {
  return `PvZCards.Engine.${namespace}.${name}, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null`;
}

function component(name, data = {}) {
  return { '$type': T('Components', name), '$data': data };
}

function query(name, data = {}) {
  return { '$type': T('Queries', name), '$data': data };
}

function effectEntity(components = []) {
  return { components };
}

const QUERY_SELF = () => query('SelfQuery');
const QUERY_TARGETABLE_FIGHTER = () => query('TargetableInPlayFighterQuery');
const QUERY_ANY_ZOMBIE_FIGHTER = () => query('CompositeAllQuery', {
  queries: [
    query('HasComponentQuery', { ComponentType: T('Components', 'Zombies') }),
    QUERY_TARGETABLE_FIGHTER()
  ]
});
const QUERY_ANY_PLANT_FIGHTER = () => query('CompositeAllQuery', {
  queries: [
    query('HasComponentQuery', { ComponentType: T('Components', 'Plants') }),
    QUERY_TARGETABLE_FIGHTER()
  ]
});

function primaryTargetFilter(queryObject, overrides = {}) {
  return component('PrimaryTargetFilter', {
    SelectionType: 'All',
    NumTargets: 0,
    TargetScopeType: 'All',
    TargetScopeSortValue: 'None',
    TargetScopeSortMethod: 'None',
    AdditionalTargetType: 'None',
    AdditionalTargetQuery: null,
    OnlyApplyEffectsOnAdditionalTargets: false,
    Query: queryObject,
    ...overrides
  });
}

export function getSkillTemplatePresets() {
  return [
    {
      id: 'play_damage_zombie',
      name: '出场：伤害僵尸',
      badge: '伤害',
      description: '出场时，对可选僵尸战斗单位造成 3 点伤害。适合作为植物单位/锦囊的起点模板。'
    },
    {
      id: 'play_damage_plant',
      name: '出场：伤害植物',
      badge: '伤害',
      description: '出场时，对可选植物战斗单位造成 3 点伤害。适合作为僵尸单位/锦囊的起点模板。'
    },
    {
      id: 'play_buff_zombie',
      name: '出场：强化僵尸',
      badge: 'Buff',
      description: '出场时，选择僵尸战斗单位，使其永久 +2/+2。'
    },
    {
      id: 'play_buff_plant',
      name: '出场：强化植物',
      badge: 'Buff',
      description: '出场时，选择植物战斗单位，使其永久 +2/+2。'
    },
    {
      id: 'death_damage_same_lane',
      name: '死亡：同路伤害',
      badge: '死亡触发',
      description: '离场/死亡时，对同一路敌方目标造成 4 点伤害。参考样本中的死亡触发结构。'
    },
    {
      id: 'play_create_card',
      name: '出场：生成卡牌',
      badge: '生成',
      description: '出场时生成指定 GUID 的卡牌。默认 CardGuid=1，可在参数面板修改。'
    }
  ];
}

export function createSkillTemplateTree(templateId, skillLibrary = {}) {
  let entities = [];
  if (templateId === 'play_damage_zombie') {
    entities = [effectEntity([
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_ZOMBIE_FIGHTER()),
      component('DamageEffectDescriptor', { DamageAmount: 3 })
    ])];
  } else if (templateId === 'play_damage_plant') {
    entities = [effectEntity([
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_PLANT_FIGHTER()),
      component('DamageEffectDescriptor', { DamageAmount: 3 })
    ])];
  } else if (templateId === 'play_buff_zombie') {
    entities = [effectEntity([
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_ZOMBIE_FIGHTER(), { SelectionType: 'Selected', NumTargets: 1 }),
      component('BuffEffectDescriptor', { AttackAmount: 2, HealthAmount: 2, BuffDuration: 'Permanent' })
    ])];
  } else if (templateId === 'play_buff_plant') {
    entities = [effectEntity([
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_PLANT_FIGHTER(), { SelectionType: 'Selected', NumTargets: 1 }),
      component('BuffEffectDescriptor', { AttackAmount: 2, HealthAmount: 2, BuffDuration: 'Permanent' })
    ])];
  } else if (templateId === 'death_damage_same_lane') {
    entities = [effectEntity([
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('DiscardFromPlayTrigger'),
      component('TriggerTargetFilter', { Query: query('CompositeAllQuery', { queries: [QUERY_SELF(), query('WillTriggerOnDeathEffectsQuery')] }) }),
      primaryTargetFilter(query('CompositeAllQuery', {
        queries: [
          query('InSameLaneQuery', { OriginEntityType: 'Self' }),
          query('HasComponentQuery', { ComponentType: T('Components', 'Zombies') }),
          QUERY_TARGETABLE_FIGHTER()
        ]
      })),
      component('DamageEffectDescriptor', { DamageAmount: 4 })
    ])];
  } else if (templateId === 'play_create_card') {
    entities = [effectEntity([
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      component('CreateCardEffectDescriptor', { CardGuid: 1, ForceFaceDown: false })
    ])];
  }
  const draft = buildTreeFromRealLogicEntities(entities, skillLibrary);
  draft.notes = [`由技能模板 ${templateId} 生成。请根据卡牌阵营、目标与参数继续调整。`];
  return draft;
}
