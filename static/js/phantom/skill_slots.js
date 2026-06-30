export const SKILL_SLOT_DEFINITIONS = [
  { id: 'trigger', title: '触发器', hint: '什么时候发动。建议只放 Trigger。', accepts: ['Trigger'], multiple: false, empty: '选择一个触发器，例如“当打出时”。' },
  { id: 'target', title: '目标', hint: '对谁生效。通常放 TargetSelector，也可先用 Query 占位。', accepts: ['TargetSelector', 'Query', 'CompositeQuery'], multiple: false, empty: '选择目标筛选或目标查询。' },
  { id: 'conditions', title: '条件', hint: '满足什么限制才执行。可放多个 Condition / Filter。', accepts: ['Condition', 'Filter'], multiple: true, empty: '可选，例如“每局一次”“仅植物方”。' },
  { id: 'queries', title: '查询 / 数值', hint: '提供数值、范围或复合查询。可放多个 Query。', accepts: ['Query', 'CompositeQuery'], multiple: true, empty: '可选，用于复杂技能的中间查询。' },
  { id: 'effects', title: '效果', hint: '最终做什么事。可放多个 Effect。', accepts: ['Effect', 'ComplexEffect'], multiple: true, empty: '选择一个或多个效果，例如造成伤害、抽牌、召唤。' }
];

function deepClone(value) {
  try { return JSON.parse(JSON.stringify(value ?? null)); }
  catch (_) { return value; }
}

export function normalizeSkillSlots(slots = {}) {
  const normalized = {
    trigger: slots.trigger || null,
    target: slots.target || null,
    conditions: Array.isArray(slots.conditions) ? slots.conditions : [],
    queries: Array.isArray(slots.queries) ? slots.queries : [],
    effects: Array.isArray(slots.effects) ? slots.effects : []
  };
  return normalized;
}

export function slotIdForNode(node) {
  const category = node?.category || node?.type || '';
  if (category === 'Trigger') return 'trigger';
  if (category === 'TargetSelector') return 'target';
  if (category === 'Condition' || category === 'Filter') return 'conditions';
  if (category === 'Query' || category === 'CompositeQuery') return 'queries';
  if (category === 'Effect' || category === 'ComplexEffect') return 'effects';
  return 'queries';
}

export function canPlaceNodeInSlot(node, slot) {
  if (!node || !slot) return false;
  const category = node.category || node.type || '';
  return slot.accepts.includes(category);
}

export function createSkillCardFromNode(node) {
  const params = deepClone(node?.default_data || {}) || {};
  return {
    uid: crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}_${Math.random()}`,
    node_id: node?.id || '',
    name: node?.name || node?.id || '未知节点',
    category: node?.category || '',
    type: node?.type || '',
    params,
    editable_params: deepClone(node?.editable_params || {}) || {},
    allowed_children: deepClone(node?.allowed_children || []) || [],
    child_prop: node?.child_prop || null,
    is_list: !!node?.is_list,
    description: node?.description || '',
    note: ''
  };
}

export function buildSkillLogicDraft(slots = {}) {
  const s = normalizeSkillSlots(slots);
  const sequence = [];
  if (s.trigger) sequence.push({ role: 'trigger', ...deepClone(s.trigger) });
  if (s.target) sequence.push({ role: 'target', ...deepClone(s.target) });
  for (const item of s.conditions) sequence.push({ role: 'condition', ...deepClone(item) });
  for (const item of s.queries) sequence.push({ role: 'query', ...deepClone(item) });
  for (const item of s.effects) sequence.push({ role: 'effect', ...deepClone(item) });
  return {
    format: 'phantom.skill_slots.v1',
    warning: '这是 Phantom Web 的技能插槽草稿，用于可视化编辑和后续转换；v0.6 默认不会直接写入游戏 EffectEntitiesDescriptor。',
    slots: deepClone(s),
    sequence
  };
}

export function summarizeSlotItem(item) {
  if (!item) return '';
  const paramKeys = Object.keys(item.params || {});
  return paramKeys.length ? `${item.node_id} · ${paramKeys.length} 个参数` : item.node_id;
}

function summarizeEntityNode(entity, index = 0) {
  const node = entity && typeof entity === 'object' ? entity : {};
  const id = node.id || node.ID || node.g || node.type || node.Type || node.$type || `entity_${index}`;
  const keys = Object.keys(node || {});
  const children = [];

  for (const key of keys) {
    const value = node[key];
    if (Array.isArray(value) && value.some(item => item && typeof item === 'object')) {
      children.push({
        key,
        kind: 'array',
        count: value.length,
        children: value.map((item, childIndex) => summarizeEntityNode(item, childIndex))
      });
    } else if (value && typeof value === 'object' && Object.keys(value).some(k => value[k] && typeof value[k] === 'object')) {
      children.push({
        key,
        kind: 'object',
        children: [summarizeEntityNode(value, 0)]
      });
    }
  }

  const scalarPreview = {};
  for (const key of keys) {
    const value = node[key];
    if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) scalarPreview[key] = value;
  }

  return {
    id: String(id),
    index,
    keys,
    scalarPreview,
    children
  };
}

export function buildRealLogicEntityTree(entities = []) {
  const list = Array.isArray(entities) ? entities : [];
  return {
    format: 'phantom.real_logic_entities.tree.v1',
    source: 'EffectEntitiesDescriptor.entities',
    warning: '这是从真实 card_data 中读取出的技能实体结构树，只负责观察和源码回写；不会强行映射为插槽卡片。',
    count: list.length,
    roots: list.map((entity, index) => summarizeEntityNode(entity, index))
  };
}
