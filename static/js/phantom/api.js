import {
  isPcAlignedConfig,
  mergePhantomConfigs,
  normalizePhantomConfig
} from './config_adapter.js';

export async function pingPhantom() {
  const response = await fetch('/api/phantom/ping');
  if (!response.ok) throw new Error('Phantom API 未响应');
  return response.json();
}

const STATIC_CONFIG_URL = '/static/data/phantom_config.json';

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) return null;
  return response.json();
}

export async function loadPhantomConfig() {
  let apiConfig = null;
  let staticConfig = null;

  try {
    apiConfig = await fetchJson('/api/phantom/config');
  } catch (_) {
    // API 不可用时走静态兜底
  }

  try {
    staticConfig = await fetchJson(STATIC_CONFIG_URL);
  } catch (_) {
    // 静态兜底同样可能不可用（纯文件打开等）
  }

  const apiNormalized = apiConfig ? normalizePhantomConfig(apiConfig) : null;
  const staticNormalized = staticConfig ? normalizePhantomConfig(staticConfig) : null;

  if (apiNormalized && isPcAlignedConfig(apiNormalized)) {
    return apiNormalized;
  }

  if (staticNormalized && isPcAlignedConfig(staticNormalized)) {
    return apiNormalized ? mergePhantomConfigs(apiNormalized, staticNormalized) : staticNormalized;
  }

  if (apiNormalized) return apiNormalized;
  if (staticNormalized) return staticNormalized;

  throw new Error('Phantom 配置资源加载失败（API 与静态兜底均不可用）');
}