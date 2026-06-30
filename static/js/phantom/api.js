export async function pingPhantom() {
  const response = await fetch('/api/phantom/ping');
  if (!response.ok) throw new Error('Phantom API 未响应');
  return response.json();
}

export async function loadPhantomConfig() {
  const response = await fetch('/api/phantom/config');
  if (!response.ok) throw new Error('Phantom 配置资源加载失败');
  return response.json();
}

export async function validatePhantomProject(cardsJson) {
  const response = await fetch('/api/phantom/validate-project', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cards_json: cardsJson || {} })
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || '工程校验失败');
  return data;
}

export async function inspectPhantomBundle({ bundleFile, targetAssetName = 'cards' }) {
  if (!bundleFile) throw new Error('请先选择原始 AssetBundle 文件');
  const formData = new FormData();
  formData.append('bundle', bundleFile);
  formData.append('target_asset_name', targetAssetName || 'cards');
  const response = await fetch('/api/phantom/inspect-bundle', { method: 'POST', body: formData });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || 'AB 包预检失败');
  return data;
}

export async function diffPhantomCards({ cardsJson, originalJson = null, bundleFile = null, targetAssetName = 'cards' }) {
  if (!cardsJson || !Object.keys(cardsJson).length) throw new Error('当前工程没有可对比的卡牌数据');
  if (!originalJson && !bundleFile) throw new Error('请先上传原始 card_data JSON，或选择原始 AB 包');

  const formData = new FormData();
  formData.append('cards_json', JSON.stringify(cardsJson));
  formData.append('target_asset_name', targetAssetName || 'cards');
  if (originalJson) formData.append('original_json', JSON.stringify(originalJson));
  if (bundleFile) formData.append('bundle', bundleFile);

  const response = await fetch('/api/phantom/diff', { method: 'POST', body: formData });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.message || '差异计算失败');
  return data;
}

export async function packPhantomBundle({ bundleFile, cardsJson, targetAssetName = 'cards', outputName = 'phantom_cards_bundle' }) {
  if (!bundleFile) throw new Error('请先选择原始 AssetBundle 文件');
  if (!cardsJson || !Object.keys(cardsJson).length) throw new Error('当前工程没有可注入的卡牌数据');

  const formData = new FormData();
  formData.append('bundle', bundleFile);
  formData.append('cards_json', JSON.stringify(cardsJson));
  formData.append('target_asset_name', targetAssetName || 'cards');
  formData.append('output_name', outputName || 'phantom_cards_bundle');

  const response = await fetch('/api/phantom/pack', {
    method: 'POST',
    body: formData
  });

  if (!response.ok) {
    let message = 'AB 包注入失败';
    try {
      const data = await response.json();
      message = data.message || message;
    } catch (_) {}
    throw new Error(message);
  }

  const blob = await response.blob();
  const disposition = response.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename\*=UTF-8''([^;]+)|filename="?([^";]+)"?/i);
  const filename = decodeURIComponent(match?.[1] || match?.[2] || outputName || 'phantom_cards_bundle');
  return { blob, filename };
}
