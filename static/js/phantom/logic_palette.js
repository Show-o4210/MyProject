/** PC 组件库树的搜索与展平。 */

function cloneFilteredNode(node, children) {
  return { ...node, children };
}

export function filterPaletteTree(palette = [], keyword = '') {
  const text = String(keyword || '').trim().toLowerCase();
  if (!text) return palette;

  const filterNode = (node) => {
    if (node.kind === 'node' || node.kind === 'preset') {
      const hay = `${node.id || ''} ${node.name || ''}`.toLowerCase();
      return hay.includes(text) ? node : null;
    }
    const filteredChildren = (node.children || [])
      .map(filterNode)
      .filter(Boolean);
    if (filteredChildren.length) return cloneFilteredNode(node, filteredChildren);
    if (String(node.name || '').toLowerCase().includes(text)) return { ...node, children: [] };
    return null;
  };

  return palette.map(filterNode).filter(Boolean);
}

export function collectReplaceCandidates(nodeId, nodeDef = {}, localization = {}) {
  const cat = nodeDef[nodeId]?.category;
  if (!cat) return [];
  return Object.entries(nodeDef)
    .filter(([id, defn]) => id !== nodeId && defn.category === cat)
    .map(([id]) => ({
      id,
      name: localization.node_names?.[id] || id
    }));
}