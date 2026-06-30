/** PC 端 LogicNodeAdapter 的 JS 移植。 */

import { deepClone } from './utils.js';

export function toEntityData(nodeId, node, parseNode, defn) {
  const data = deepClone(node.params || {}, {});

  if (nodeId === 'PrimaryTargetFilter' || nodeId === 'SecondaryTargetFilter') {
    let mainQuery = null;
    let addQuery = null;
    for (const child of node.children || []) {
      if (child.disabled) continue;
      if (child.node_id === 'AdditionalTargetQuery') {
        if (child.children?.length) addQuery = parseNode(child.children[0]);
      } else if (mainQuery === null) {
        mainQuery = parseNode(child);
      }
    }
    data.Query = mainQuery;
    data.AdditionalTargetQuery = addQuery;
    return data;
  }

  if (nodeId === 'QueryEntityCondition') {
    for (const child of node.children || []) {
      if (child.disabled) continue;
      if (child.node_id === 'FinderPlaceholder' && child.children?.length) {
        data.Finder = parseNode(child.children[0]);
      } else if (child.node_id === 'QueryPlaceholder' && child.children?.length) {
        data.Query = parseNode(child.children[0]);
      }
    }
    return data;
  }

  const childProp = defn?.child_prop;
  if (childProp) {
    const childData = (node.children || [])
      .filter(child => !child.disabled)
      .map(child => parseNode(child))
      .filter(Boolean);
    data[childProp] = defn.is_list ? childData : (childData[0] ?? null);
  }
  return data;
}

export function extractBuildData(nodeId, cdata, defn) {
  const params = {};
  const children = [];

  if (nodeId === 'PrimaryTargetFilter' || nodeId === 'SecondaryTargetFilter') {
    for (const [k, v] of Object.entries(cdata || {})) {
      if (k === 'Query') {
        if (v) children.push(['main', v]);
      } else if (k === 'AdditionalTargetQuery') {
        if (v) children.push(['additional', v]);
      } else {
        params[k] = v;
      }
    }
    if (params.AdditionalTargetType === 'Query' && !children.some(([t]) => t === 'additional')) {
      children.push(['additional', null]);
    }
    return { params, children };
  }

  if (nodeId === 'QueryEntityCondition') {
    for (const [k, v] of Object.entries(cdata || {})) {
      if (k === 'Finder') {
        if (v) children.push(['finder', v]);
      } else if (k === 'Query') {
        if (v) children.push(['query', v]);
      } else {
        params[k] = v;
      }
    }
    return { params, children };
  }

  const childProp = defn?.child_prop;
  for (const [k, v] of Object.entries(cdata || {})) {
    if (k === childProp) {
      const list = Array.isArray(v) ? v : [v];
      for (const item of list) {
        if (item) children.push(['normal', item]);
      }
    } else {
      params[k] = v;
    }
  }
  return { params, children };
}

export function buildSpecialChildren(parentNode, childrenData, buildNode) {
  for (const [childType, childComp] of childrenData) {
    if (childType === 'additional') {
      const folder = {
        node_id: 'AdditionalTargetQuery',
        params: {},
        disabled: false,
        children: childComp ? [buildNode(childComp)] : []
      };
      parentNode.children = parentNode.children || [];
      parentNode.children.push(folder);
    } else if (childType === 'finder' || childType === 'query') {
      const placeholderId = childType === 'finder' ? 'FinderPlaceholder' : 'QueryPlaceholder';
      const placeholder = {
        node_id: placeholderId,
        params: {},
        disabled: false,
        children: childComp ? [buildNode(childComp)] : []
      };
      parentNode.children = parentNode.children || [];
      parentNode.children.push(placeholder);
    } else if (childComp) {
      parentNode.children = parentNode.children || [];
      parentNode.children.push(buildNode(childComp));
    }
  }
}

export function toSnapshotDict(nodeId, node, parseDict) {
  if (nodeId === 'QueryEntityCondition') {
    let finderData = null;
    let queryData = null;
    for (const child of node.children || []) {
      if (child.node_id === 'FinderPlaceholder' && child.children?.length) {
        finderData = parseDict(child.children[0]);
      } else if (child.node_id === 'QueryPlaceholder' && child.children?.length) {
        queryData = parseDict(child.children[0]);
      }
    }
    return {
      node_id: nodeId,
      params: deepClone(node.params || {}, {}),
      disabled: !!node.disabled,
      finder: finderData,
      query: queryData
    };
  }

  if (nodeId === 'EffectValueDescriptor') {
    const params = deepClone(node.params || {}, {});
    const mappingType = params.MappingType || 'DamageToHeal';
    const destToSourceMap = mappingType === 'DamageToHeal'
      ? { HealAmount: 'DamageAmount' }
      : { DamageAmount: 'HealAmount' };
    return {
      node_id: nodeId,
      params: { DestToSourceMap: destToSourceMap },
      disabled: !!node.disabled,
      children: []
    };
  }

  return {
    node_id: nodeId,
    params: deepClone(node.params || {}, {}),
    disabled: !!node.disabled,
    children: (node.children || []).map(child => parseDict(child))
  };
}

export function restoreSnapshotChildren(nodeId, parentNode, dataDict, restoreNode) {
  if (nodeId === 'QueryEntityCondition') {
    const finder = {
      node_id: 'FinderPlaceholder',
      params: {},
      disabled: false,
      children: dataDict.finder ? [restoreNode(dataDict.finder)] : []
    };
    const query = {
      node_id: 'QueryPlaceholder',
      params: {},
      disabled: false,
      children: dataDict.query ? [restoreNode(dataDict.query)] : []
    };
    parentNode.children = [finder, query];
    return;
  }
  parentNode.children = (dataDict.children || []).map(sub => restoreNode(sub));
}