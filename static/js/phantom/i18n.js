export function createTranslator(config) {
  return function translate(key, fallback = '') {
    const lang = config.language || config.default_language || 'zh-CN';
    const table = config.localization?.[lang] || config.localization?.['zh-CN'] || {};
    return table[key] || fallback || key;
  };
}

export function labelOf(item) {
  if (!item) return '';
  return item.name || item.label || item.value || item.id || '';
}
