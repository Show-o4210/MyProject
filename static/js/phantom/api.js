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

async function fetchCardIndex() {
  const data = await fetchJson('/api/phantom/card-index');
  if (!data?.card_index?.length) return null;
  return {
    card_index: data.card_index,
    card_index_meta: data.card_index_meta || {
      source: 'data/index.json',
      count: data.card_index.length,
      loaded: true,
      error: ''
    }
  };
}

function applyCardIndex(config, cardIndexBundle) {
  if (!config || !cardIndexBundle) return config;
  return {
    ...config,
    card_index: cardIndexBundle.card_index,
    card_index_meta: cardIndexBundle.card_index_meta
  };
}

export async function loadPhantomConfig() {
  let apiConfig = null;
  let staticConfig = null;
  let cardIndexBundle = null;

  const requests = [
    fetchJson('/api/phantom/config').then((v) => { apiConfig = v; }).catch(() => {}),
    fetchJson(STATIC_CONFIG_URL).then((v) => { staticConfig = v; }).catch(() => {}),
    fetchCardIndex().then((v) => { cardIndexBundle = v; }).catch(() => {})
  ];
  await Promise.all(requests);

  const apiNormalized = apiConfig ? normalizePhantomConfig(apiConfig) : null;
  const staticNormalized = staticConfig ? normalizePhantomConfig(staticConfig) : null;

  let config = null;
  if (apiNormalized && isPcAlignedConfig(apiNormalized)) {
    config = apiNormalized;
  } else if (staticNormalized && isPcAlignedConfig(staticNormalized)) {
    config = apiNormalized ? mergePhantomConfigs(apiNormalized, staticNormalized) : staticNormalized;
  } else if (apiNormalized) {
    config = apiNormalized;
  } else if (staticNormalized) {
    config = staticNormalized;
  }

  if (!config) {
    throw new Error('Phantom 配置资源加载失败（API 与静态兜底均不可用）');
  }

  return applyCardIndex(config, cardIndexBundle);
}