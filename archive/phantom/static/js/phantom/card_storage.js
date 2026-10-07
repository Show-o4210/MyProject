import {readBoundedJson, validateJson, checkText} from '../json_budget.js';
import { STORAGE_KEY, createEmptyCard } from './state.js';

const LEGACY_STORAGE_KEY = 'pvzh_phantom_json_creator_v11';

export async function loadCard() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = await readBoundedJson(raw);
      if (parsed?.card && typeof parsed.card === 'object' && !Array.isArray(parsed.card)) return parsed.card;
      throw new Error('草稿格式无效');
    }
    const legacyRaw = localStorage.getItem(LEGACY_STORAGE_KEY);
    if (legacyRaw) {
      const legacy = await readBoundedJson(legacyRaw);
      if (legacy?.cards?.[0] && typeof legacy.cards[0] === 'object' && !Array.isArray(legacy.cards[0])) return legacy.cards[0];
      throw new Error('旧草稿格式无效');
    }
  } catch (error) {
    console.warn('无法读取本地草稿，已重置。', error);
    clearCardStorage();
    document.getElementById('draft-recovery')?.removeAttribute('hidden');
  }
  return createEmptyCard();
}

export function saveCard(card) {
  validateJson(card);
  const data = { card, updatedAt: new Date().toISOString() };
  const encoded = JSON.stringify(data);
  checkText(encoded);
  localStorage.setItem(STORAGE_KEY, encoded);
  return data;
}

export function clearCardStorage() {
  localStorage.removeItem(STORAGE_KEY);
  localStorage.removeItem(LEGACY_STORAGE_KEY);
}

export function downloadJson(filename, data) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function readJsonFile(file) {
  return readBoundedJson(file);
}
