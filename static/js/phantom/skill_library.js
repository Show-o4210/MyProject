export function flattenSkillNodes(skillLibrary) {
  const categories = skillLibrary?.categories || [];
  return categories.flatMap(category => (category.nodes || []).map(node => ({ ...node, categoryName: category.name })));
}

export function filterSkillCategories(skillLibrary, keyword) {
  const text = String(keyword || '').trim().toLowerCase();
  const categories = skillLibrary?.categories || [];
  if (!text) return categories;

  return categories
    .map(category => ({
      ...category,
      nodes: (category.nodes || []).filter(node => {
        return [node.id, node.name, node.type, node.description].some(value => String(value || '').toLowerCase().includes(text));
      })
    }))
    .filter(category => category.nodes.length > 0);
}
