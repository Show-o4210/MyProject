/** 将 API 响应与静态配置统一为前端可用结构。 */

export function isPcAlignedConfig(config) {
  return !!(
    config
    && Array.isArray(config.palette)
    && config.palette.length > 0
    && config.node_def
    && Object.keys(config.node_def).length > 0
  );
}

export function normalizePhantomConfig(raw = {}) {
  if (!raw || typeof raw !== 'object') return raw;

  return {
    ...raw,
    node_def: raw.node_def || {},
    palette: raw.palette || [],
    localization: {
      node_names: raw.localization?.node_names || {},
      param_names: raw.localization?.param_names || {},
      enum_names: raw.localization?.enum_names || {}
    },
    skill_library: raw.skill_library || { categories: [], total_nodes: 0 },
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
