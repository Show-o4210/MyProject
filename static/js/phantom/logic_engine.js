/**
 * PC 对齐的技能逻辑引擎：AbilityGroup + node_id 语义树。
 */

import {
  toEntityData,
  extractBuildData,
  buildSpecialChildren,
  toSnapshotDict,
  restoreSnapshotChildren
} from './logic_node_adapter.js';
import { ASSEMBLY_SUFFIX, deepClone, makeUid } from './utils.js';

export const SKILL_TREE_FORMAT = 'phantom.skill_tree.v3';
export { ASSEMBLY_SUFFIX };

const VIRTUAL_NODES = new Set([
  'AbilityGroup',
  'AdditionalTargetQuery',
  'FinderPlaceholder',
  'QueryPlaceholder'
]);

const COMPONENT_PICKER_OPTIONS = [
  'PvZCards.Engine.Components.Zombies, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null',
  'PvZCards.Engine.Components.Plants, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null',
  'PvZCards.Engine.Components.Lane, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null',
  'PvZCards.Engine.Components.FaceDown, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null',
  'PvZCards.Engine.Components.Environment, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null'
];

const TERRAIN_PICKER_OPTIONS = [
  'PvZCards.Engine.Components.GrassTerrain, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null',
  'PvZCards.Engine.Components.WaterTerrain, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null',
  'PvZCards.Engine.Components.HighgroundTerrain, EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null'
];

function refreshUids(node) {
  node.uid = makeUid('tree');
  (node.children || []).forEach(refreshUids);
  return node;
}

export function normalizeLogicTreeDraft(input = {}) {
  const roots = Array.isArray(input?.roots) ? input.roots : [];
  return {
    format: input?.format || SKILL_TREE_FORMAT,
    version: input?.version || 3,
    roots: roots.map(normalizeTreeNode),
    notes: input?.notes || []
  };
}

export function normalizeTreeNode(node = {}) {
  return {
    uid: node.uid || makeUid('tree'),
    node_id: node.node_id || node.id || 'UnknownNode',
    params: deepClone(node.params ?? {}, {}),
    disabled: node.disabled === true,
    collapsed: node.collapsed === true,
    children: Array.isArray(node.children) ? node.children.map(normalizeTreeNode) : []
  };
}

export function createNodeFromDef(nodeId, nodeDef = {}, overrides = {}) {
  const params = deepClone(overrides.params ?? nodeDef.default_data ?? {}, {});
  const node = normalizeTreeNode({
    uid: makeUid('tree'),
    node_id: nodeId,
    params,
    disabled: false,
    children: []
  });

  if (nodeId === 'QueryEntityCondition') {
    node.children = [
      normalizeTreeNode({ node_id: 'FinderPlaceholder', params: {}, children: [] }),
      normalizeTreeNode({ node_id: 'QueryPlaceholder', params: {}, children: [] })
    ];
  }
  return node;
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

export function flattenSkillTree(roots = [], localization = {}) {
  const rows = [];
  const walk = (nodes, depth = 0) => {
    for (const node of nodes || []) {
      rows.push({
        node,
        depth,
        hasChildren: !!(node.children && node.children.length),
        label: nodeDisplayLabel(node, localization),
        paramText: nodeParamText(node, localization)
      });
      if (!node.collapsed) walk(node.children || [], depth + 1);
    }
  };
  walk(roots, 0);
  return rows;
}

export function nodeDisplayLabel(node, localization = {}) {
  const nodeId = node?.node_id;
  const names = localization.node_names || {};
  if (nodeId === 'AbilityGroup') return '📦 技能组';
  if (nodeId === 'AdditionalTargetQuery') return names.AdditionalTargetQuery || '📦 额外目标条件';
  if (nodeId === 'FinderPlaceholder') return '🔍 查找范围 (Finder)';
  if (nodeId === 'QueryPlaceholder') return '📋 满足条件 (Query)';
  return names[nodeId] || nodeId || '未知节点';
}

export function nodeParamText(node, localization = {}, nodeDef = {}) {
  const nodeId = node?.node_id;
  const defn = nodeDef[nodeId] || {};
  const editableKeys = Object.keys(defn.editable_params || {});
  const params = node?.params || {};
  const paramNames = localization.param_names || {};
  const enumNames = localization.enum_names || {};
  if (!editableKeys.length || !Object.keys(params).length) return '';
  return editableKeys
    .filter(k => params[k] !== undefined)
    .map(k => {
      const v = params[k];
      const label = enumNames[v] || v;
      return `${paramNames[k] || k}: ${label}`;
    })
    .join('，');
}

export function treeNodeSummary(node, localization = {}, nodeDef = {}) {
  const text = nodeParamText(node, localization, nodeDef);
  const childCount = node?.children?.length || 0;
  const pieces = [];
  if (text) pieces.push(text);
  if (childCount) pieces.push(`${childCount} 个子节点`);
  if (node?.disabled) pieces.push('已禁用');
  return pieces.join(' · ') || '无参数';
}

export function canInsertNode(parentNodeId, childNodeId, nodeDef = {}) {
  const childDefn = nodeDef[childNodeId] || {};
  const cat = childDefn.category;

  if (['OncePerGameCondition', 'OncePerTurnCondition', 'PersistsAfterTransform'].includes(childNodeId)) {
    return parentNodeId === 'AbilityGroup';
  }
  if (parentNodeId === 'FinderPlaceholder' || parentNodeId === 'QueryPlaceholder') {
    return cat === 'CompositeQuery' || cat === 'Query';
  }
  if (parentNodeId === 'AbilityGroup') {
    return ['Trigger', 'Filter', 'TargetSelector', 'Effect', 'Framework', 'ComplexEffect'].includes(cat);
  }
  if (parentNodeId === 'AdditionalTargetQuery') {
    return cat === 'CompositeQuery' || cat === 'Query';
  }

  const parentDefn = nodeDef[parentNodeId] || {};
  const allowed = parentDefn.allowed_children || [];
  return allowed.includes(cat) || allowed.includes(childNodeId);
}

export function addChildNode(roots, parentUid, newNode, nodeDef = {}) {
  if (!parentUid) {
    roots.push(newNode);
    return { ok: true, node: newNode };
  }
  const { node: parent } = findNodeAndParent(roots, parentUid);
  if (!parent) return { ok: false, error: '未找到父节点' };
  if (!canInsertNode(parent.node_id, newNode.node_id, nodeDef)) {
    return { ok: false, error: '当前位置无法插入该组件' };
  }
  parent.children = Array.isArray(parent.children) ? parent.children : [];
  parent.children.push(newNode);
  parent.collapsed = false;
  return { ok: true, node: newNode };
}

export function removeTreeNode(roots, uid) {
  const found = findNodeAndParent(roots, uid);
  if (!found.node || found.index < 0) return false;
  if (found.node.node_id === 'EffectEntityGrouping') return false;
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
  const cloned = refreshUids(normalizeTreeNode(deepClone(node, {})));
  return cloned;
}

export function duplicateTreeNode(roots, uid) {
  const found = findNodeAndParent(roots, uid);
  if (!found.node || found.index < 0) return null;
  const cloned = cloneTreeNode(found.node);
  found.list.splice(found.index + 1, 0, cloned);
  return cloned;
}

export function replaceTreeNode(node, newNodeId, nodeDef = {}) {
  const newDefn = nodeDef[newNodeId];
  if (!newDefn) return false;
  const oldParams = node.params || {};
  const newParams = deepClone(newDefn.default_data || {}, {});
  for (const [k, v] of Object.entries(oldParams)) {
    if (newDefn.editable_params?.[k] !== undefined) newParams[k] = v;
  }
  node.node_id = newNodeId;
  node.params = newParams;
  if (newNodeId === 'QueryEntityCondition') {
    node.children = [
      normalizeTreeNode({ node_id: 'FinderPlaceholder', params: {}, children: [] }),
      normalizeTreeNode({ node_id: 'QueryPlaceholder', params: {}, children: [] })
    ];
  } else if (!newDefn.child_prop) {
    node.children = [];
  }
  return true;
}

export function resolveNodeIdFromComponent(compDict, nodeDef = {}) {
  const fullType = compDict?.$type || '';
  const cdata = compDict?.$data || {};
  for (const [nodeId, defn] of Object.entries(nodeDef)) {
    if (!defn.type || !fullType.includes(defn.type)) continue;
    if (fullType.includes('HasComponentQuery')) {
      const defaultCt = defn.default_data?.ComponentType || '';
      if (defaultCt === cdata.ComponentType) return nodeId;
      continue;
    }
    return nodeId;
  }
  return null;
}

export function buildTreeNodeFromComponent(compDict, nodeDef = {}) {
  const nodeId = resolveNodeIdFromComponent(compDict, nodeDef);
  if (!nodeId) return null;
  const defn = nodeDef[nodeId];
  const { params, children } = extractBuildData(nodeId, compDict.$data || {}, defn);
  const node = normalizeTreeNode({ node_id: nodeId, params, children: [] });
  buildSpecialChildren(node, children, (childComp) => buildTreeNodeFromComponent(childComp, nodeDef));
  return node;
}

export function buildTreeFromLogicEntities(entities = [], nodeDef = {}) {
  const roots = [];
  for (const entity of Array.isArray(entities) ? entities : []) {
    const group = normalizeTreeNode({ node_id: 'AbilityGroup', params: {}, children: [] });
    for (const comp of entity?.components || []) {
      const built = buildTreeNodeFromComponent(comp, nodeDef);
      if (built) group.children.push(built);
    }
    roots.push(group);
  }
  return normalizeLogicTreeDraft({ roots, notes: ['由 logicEntities 按 PC 语义结构树解析。'] });
}

export function parseNodeToComponent(node, nodeDef = {}) {
  if (node.disabled) return null;
  const nodeId = node.node_id;
  if (nodeId === 'AdditionalTargetQuery') {
    return node.children?.length ? parseNodeToComponent(node.children[0], nodeDef) : null;
  }
  if (VIRTUAL_NODES.has(nodeId) && nodeId !== 'AbilityGroup') return null;
  const defn = nodeDef[nodeId];
  if (!defn) return null;
  const data = toEntityData(nodeId, node, (child) => parseNodeToComponent(child, nodeDef), defn);
  return {
    '$type': `${defn.type}${ASSEMBLY_SUFFIX}`,
    '$data': data
  };
}

export function parseTreeToLogicEntities(roots = [], nodeDef = {}) {
  const entities = [];
  for (const root of roots || []) {
    if (root.disabled) continue;
    if (root.node_id === 'AbilityGroup') {
      const components = (root.children || [])
        .map(child => parseNodeToComponent(child, nodeDef))
        .filter(Boolean);
      if (components.length) entities.push({ components });
      continue;
    }
    const single = parseNodeToComponent(root, nodeDef);
    if (single) entities.push({ components: [single] });
  }
  return entities;
}

export function parseNodeToSnapshot(node) {
  return toSnapshotDict(node.node_id, node, (child) => parseNodeToSnapshot(child));
}

export function restoreNodeFromSnapshot(dataDict, nodeDef = {}) {
  const nodeId = dataDict.node_id;
  const node = normalizeTreeNode({
    node_id: nodeId,
    params: deepClone(dataDict.params || {}, {}),
    disabled: !!dataDict.disabled,
    children: []
  });
  restoreSnapshotChildren(nodeId, node, dataDict, (sub) => restoreNodeFromSnapshot(sub, nodeDef));

  if (nodeId === 'MoveCardToLanesEffectDescriptor') {
    // PC 端会在技能组下自动补 SecondaryTargetFilter，Web 保持手动添加即可。
  }
  if (nodeId === 'PrimaryTargetFilter' || nodeId === 'SecondaryTargetFilter') {
    if (node.params.AdditionalTargetType === 'Query') {
      const hasFolder = (node.children || []).some(c => c.node_id === 'AdditionalTargetQuery');
      if (!hasFolder) {
        node.children = node.children || [];
        node.children.push(normalizeTreeNode({ node_id: 'AdditionalTargetQuery', params: {}, children: [] }));
      }
    }
  }
  return node;
}

export function restoreTreeFromSnapshot(snapshot = []) {
  return (Array.isArray(snapshot) ? snapshot : []).map(item => restoreNodeFromSnapshot(item));
}

export function addAbilityGroup(roots, nodeDef = {}) {
  const group = normalizeTreeNode({ node_id: 'AbilityGroup', params: {}, children: [] });
  const framework = createNodeFromDef('EffectEntityGrouping', nodeDef['EffectEntityGrouping'] || {});
  group.children.push(framework);
  roots.push(group);
  return group;
}

export function onParamUpdated(node, key, value, nodeDef = {}) {
  if (!node?.params) node.params = {};
  node.params[key] = value;
  if (
    (node.node_id === 'PrimaryTargetFilter' || node.node_id === 'SecondaryTargetFilter')
    && key === 'AdditionalTargetType'
  ) {
    const children = node.children || [];
    const idx = children.findIndex(c => c.node_id === 'AdditionalTargetQuery');
    if (value === 'Query' && idx < 0) {
      children.push(normalizeTreeNode({ node_id: 'AdditionalTargetQuery', params: {}, children: [] }));
      node.children = children;
    } else if (value !== 'Query' && idx >= 0) {
      children.splice(idx, 1);
      node.children = children;
    }
  }
  if (node.node_id === 'PrimaryTargetFilter' && key === 'SelectionType') {
    if (['All', 'Manual'].includes(value)) node.params.NumTargets = 0;
  }
}

export function getInspectorFields(node, nodeDef = {}, localization = {}) {
  const nodeId = node?.node_id;
  if (!nodeId || nodeId === 'AbilityGroup') return [];
  const schema = nodeDef[nodeId]?.editable_params || {};
  const paramNames = localization.param_names || {};
  const enumNames = localization.enum_names || {};
  return Object.entries(schema).map(([key, config]) => ({
    key,
    label: paramNames[key] || key,
    config,
    enumNames,
    options: config.type === 'component_picker'
      ? COMPONENT_PICKER_OPTIONS
      : config.type === 'terrain_picker'
        ? TERRAIN_PICKER_OPTIONS
        : config.options || []
  }));
}

export function formatEnumLabel(value, enumNames = {}) {
  return enumNames[value] || value;
}

// ── 快速模板（与 PC 样本结构一致）──

function T(namespace, name) {
  return `PvZCards.Engine.${namespace}.${name}${ASSEMBLY_SUFFIX}`;
}

function component(name, data = {}) {
  return { '$type': T('Components', name), '$data': data };
}

function query(name, data = {}) {
  return { '$type': T('Queries', name), '$data': data };
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
    { id: 'play_damage_zombie', name: '出场：伤害僵尸', badge: '伤害', description: '出场时，对可选僵尸战斗单位造成 3 点伤害。' },
    { id: 'play_damage_plant', name: '出场：伤害植物', badge: '伤害', description: '出场时，对可选植物战斗单位造成 3 点伤害。' },
    { id: 'play_buff_zombie', name: '出场：强化僵尸', badge: 'Buff', description: '出场时，选择僵尸战斗单位，使其永久 +2/+2。' },
    { id: 'play_buff_plant', name: '出场：强化植物', badge: 'Buff', description: '出场时，选择植物战斗单位，使其永久 +2/+2。' },
    { id: 'death_damage_same_lane', name: '死亡：同路伤害', badge: '死亡触发', description: '离场/死亡时，对同一路敌方目标造成 4 点伤害。' },
    { id: 'play_create_card', name: '出场：生成卡牌', badge: '生成', description: '出场时生成指定 GUID 的卡牌。' }
  ];
}

export function createSkillTemplateTree(templateId, nodeDef = {}) {
  let entities = [];
  if (templateId === 'play_damage_zombie') {
    entities = [{ components: [
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_ZOMBIE_FIGHTER()),
      component('DamageEffectDescriptor', { DamageAmount: 3 })
    ] }];
  } else if (templateId === 'play_damage_plant') {
    entities = [{ components: [
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_PLANT_FIGHTER()),
      component('DamageEffectDescriptor', { DamageAmount: 3 })
    ] }];
  } else if (templateId === 'play_buff_zombie') {
    entities = [{ components: [
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_ZOMBIE_FIGHTER(), { SelectionType: 'Manual', NumTargets: 1 }),
      component('BuffEffectDescriptor', { AttackAmount: 2, HealthAmount: 2, BuffDuration: 'Permanent' })
    ] }];
  } else if (templateId === 'play_buff_plant') {
    entities = [{ components: [
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      primaryTargetFilter(QUERY_ANY_PLANT_FIGHTER(), { SelectionType: 'Manual', NumTargets: 1 }),
      component('BuffEffectDescriptor', { AttackAmount: 2, HealthAmount: 2, BuffDuration: 'Permanent' })
    ] }];
  } else if (templateId === 'death_damage_same_lane') {
    entities = [{ components: [
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
    ] }];
  } else if (templateId === 'play_create_card') {
    entities = [{ components: [
      component('EffectEntityGrouping', { AbilityGroupId: 0 }),
      component('PlayTrigger'),
      component('TriggerTargetFilter', { Query: QUERY_SELF() }),
      component('CreateCardEffectDescriptor', { CardGuid: 1, ForceFaceDown: false })
    ] }];
  }
  return buildTreeFromLogicEntities(entities, nodeDef);
}

export function treeHasContent(roots = []) {
  if (!Array.isArray(roots) || !roots.length) return false;
  return roots.some(root => {
    if (root?.real_kind) return false;
    if (root?.node_id === 'AbilityGroup') return (root.children?.length || 0) > 0;
    return !!root?.node_id;
  });
}

export function migrateLegacyTreeDraft(draft, logicEntities = [], nodeDef = {}) {
  const hasEntities = Array.isArray(logicEntities) && logicEntities.length > 0;
  const normalized = normalizeLogicTreeDraft(draft || {});
  const isCurrentFormat = normalized.format === SKILL_TREE_FORMAT;
  const contentOk = treeHasContent(normalized.roots);

  if (hasEntities && (!contentOk || !isCurrentFormat)) {
    return buildTreeFromLogicEntities(logicEntities, nodeDef);
  }
  if (contentOk && isCurrentFormat) return normalized;
  if (hasEntities) return buildTreeFromLogicEntities(logicEntities, nodeDef);
  return normalized;
}