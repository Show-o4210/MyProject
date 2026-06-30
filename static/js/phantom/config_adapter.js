/** 将旧版 API 响应与 PC 对齐格式统一为前端可用结构。 */

import { ASSEMBLY_SUFFIX } from './utils.js';

export function isPcAlignedConfig(config) {
  return !!(
    config
    && Array.isArray(config.palette)
    && config.palette.length > 0
    && config.node_def
    && Object.keys(config.node_def).length > 0
  );
}

export function parseLegacyLocalization(loc = {}) {
  if (loc?.node_names) {
    return {
      node_names: loc.node_names || {},
      param_names: loc.param_names || {},
      enum_names: loc.enum_names || {}
    };
  }

  const zh = loc['zh-CN'] || loc['zh-cn'] || {};
  const node_names = {};
  const param_names = {};
  const enum_names = {};

  for (const [key, value] of Object.entries(zh)) {
    if (key.startsWith('node.')) node_names[key.slice(5)] = value;
    else if (key.startsWith('param.')) param_names[key.slice(6)] = value;
    else if (key.startsWith('enum.')) enum_names[key.slice(5)] = value;
  }

  return { node_names, param_names, enum_names };
}

export function buildNodeDefFromSkillLibrary(skillLibrary = {}) {
  const nodeDef = {};
  for (const category of skillLibrary.categories || []) {
    for (const node of category.nodes || []) {
      if (!node?.id) continue;
      nodeDef[node.id] = {
        id: node.id,
        type: node.type || '',
        category: node.category || category.id || '',
        default_data: node.default_data || {},
        editable_params: node.editable_params || {},
        child_prop: node.child_prop ?? null,
        is_list: !!node.is_list,
        allowed_children: node.allowed_children || [],
        full_type: node.type ? `${node.type}${ASSEMBLY_SUFFIX}` : ''
      };
    }
  }
  return nodeDef;
}

export function buildPaletteFromSkillLibrary(skillLibrary = {}) {
  return (skillLibrary.categories || []).map((category) => ({
    id: category.id,
    kind: 'category',
    name: category.name || category.id,
    children: (category.nodes || []).map((node) => ({
      kind: 'node',
      id: node.id,
      name: node.name || node.id,
      category: category.id
    }))
  })).filter((group) => group.children.length > 0);
}

export function normalizePhantomConfig(raw = {}) {
  if (!raw || typeof raw !== 'object') return raw;

  const localization = parseLegacyLocalization(raw.localization);
  const skillLibrary = raw.skill_library || { categories: [], total_nodes: 0 };

  let nodeDef = raw.node_def || {};
  let palette = raw.palette || [];

  if (!Object.keys(nodeDef).length && skillLibrary.categories?.length) {
    nodeDef = buildNodeDefFromSkillLibrary(skillLibrary);
  }
  if (!palette.length && skillLibrary.categories?.length) {
    palette = buildPaletteFromSkillLibrary(skillLibrary);
  }

  return {
    ...raw,
    node_def: nodeDef,
    palette,
    localization,
    skill_library: skillLibrary,
    user_presets: raw.user_presets || {}
  };
}

export function mergePhantomConfigs(primary = {}, secondary = {}) {
  const merged = normalizePhantomConfig({ ...secondary, ...primary });
  if (!isPcAlignedConfig(merged) && isPcAlignedConfig(secondary)) {
    return normalizePhantomConfig({
      ...secondary,
      enums: primary.enums?.factions?.length ? primary.enums : secondary.enums,
      card_index: primary.card_index?.length ? primary.card_index : secondary.card_index,
      card_index_meta: primary.card_index_meta?.loaded ? primary.card_index_meta : secondary.card_index_meta
    });
  }
  return merged;
}