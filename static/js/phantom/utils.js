export const ASSEMBLY_SUFFIX =
  ', EngineLib, Version=1.0.0.0, Culture=neutral, PublicKeyToken=null';

export function deepClone(value, fallback = null) {
  try {
    if (value === undefined || value === null) return fallback;
    return JSON.parse(JSON.stringify(value));
  } catch (_) {
    return fallback;
  }
}

export function makeUid(prefix = 'node') {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2)}`;
}