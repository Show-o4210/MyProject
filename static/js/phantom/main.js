import {
  tabs, logicWorkspaceTabs,
  fallbackOptions, emptyConfig, labelOf,
  createEmptyCard
} from './state.js';
import { loadCard, saveCard, clearCardStorage, downloadJson, readJsonFile } from './card_storage.js';
import { pingPhantom, loadPhantomConfig } from './api.js';
import { filterPaletteTree, collectReplaceCandidates } from './logic_palette.js';
import {
  normalizeLogicTreeDraft, createNodeFromDef, flattenSkillTree,
  findNodeAndParent, addChildNode, removeTreeNode, moveTreeNode, duplicateTreeNode,
  treeNodeSummary, buildTreeFromLogicEntities, parseTreeToLogicEntities,
  getSkillTemplatePresets, createSkillTemplateTree, migrateLegacyTreeDraft,
  addAbilityGroup, replaceTreeNode, onParamUpdated, getInspectorFields,
  formatEnumLabel, restoreNodeFromSnapshot, canInsertNode, treeHasContent
} from './logic_engine.js';
import {
  createLogicHistory, saveHistorySnapshot, canUndo, canRedo, undoHistory, redoHistory, clearHistory
} from './logic_history.js';
import {
  generateGameCardEntry,
  cardFormFromGameEntry, extractEntryFromImportedJson
} from './card_serializer.js';

const { createApp } = Vue;

createApp({
  delimiters: ['[[', ']]'],
  data() {
    return {
      tabs,
      logicWorkspaceTabs,
      options: { ...fallbackOptions },
      phantomConfig: { ...emptyConfig },
      card: loadCard(),
      activeTab: 'basic',
      newSubtype: { id: '', name: '' },
      abilitySearch: '',
      newTriggeredAbilityType: 'DoubleStrike',
      customTriggeredAbility: { g: 0, vt: 0, va: 0 },
      importGuid: '',
      skillSearch: '',
      selectedPaletteItem: null,
      logicWorkspace: 'tree',
      selectedSkillTreeNodeUid: '',
      expandedPaletteGroups: {},
      logicHistory: createLogicHistory(),
      showReplaceMenu: false,
      mobileMenuOpen: false,
      viewportWidth: typeof window !== 'undefined' ? window.innerWidth : 1280,
      viewportHeight: typeof window !== 'undefined' ? window.innerHeight : 800,
      toastMessage: '',
      toastTimer: null,
      configStatus: 'loading',
      logicTreeRevision: 0,
      _syncingLogic: false
    };
  },
  computed: {
    currentTab() {
      return this.tabs.find(tab => tab.id === this.activeTab) || this.tabs[0];
    },
    cardIndexInfo() {
      return this.findCardIndexInfo(this.card);
    },
    nodeDef() {
      return this.phantomConfig.nodeDef || {};
    },
    logicLocalization() {
      return this.phantomConfig.localization || { node_names: {}, param_names: {}, enum_names: {} };
    },
    filteredPalette() {
      return filterPaletteTree(this.phantomConfig.palette || [], this.skillSearch);
    },
    gameCardJson() {
      return generateGameCardEntry(this.card, this.phantomConfig);
    },
    previewJson() {
      return JSON.stringify(this.gameCardJson, null, 2);
    },
    filteredSpecialAbilities() {
      const q = (this.abilitySearch || '').toLowerCase().trim();
      const list = this.options.specialAbilities || [];
      if (!q) return list;
      return list.filter(item => `${item.id} ${item.name} ${item.type || ''}`.toLowerCase().includes(q));
    },
    selectedSpecialAbilityDetails() {
      const selected = new Set(this.card.specialAbilities || []);
      return (this.options.specialAbilities || []).filter(item => selected.has(item.id));
    },
    triggeredAbilityPresets() {
      return [
        { id: 'DoubleStrike', name: '💥 双重攻击', data: { g: 562, vt: 0, va: 0 } },
        { id: 'Overshoot', name: '🎯 先攻', data: { g: 564, vt: 1, va: 2 } },
        { id: 'Custom', name: '🧩 自定义', data: null }
      ];
    },
    skillTemplatePresets() {
      return getSkillTemplatePresets();
    },
    skillTreeDraft() {
      return this.card.skillTreeDraft || normalizeLogicTreeDraft();
    },
    skillTreeRows() {
      void this.logicTreeRevision;
      return flattenSkillTree(this.skillTreeDraft.roots || [], this.logicLocalization);
    },
    selectedSkillTreeNode() {
      void this.logicTreeRevision;
      return findNodeAndParent(this.skillTreeDraft.roots || [], this.selectedSkillTreeNodeUid).node;
    },
    selectedSkillTreeNodeJson() {
      return this.selectedSkillTreeNode ? JSON.stringify(this.selectedSkillTreeNode, null, 2) : '';
    },
    realLogicEntitiesJson() {
      return JSON.stringify(this.card.logicEntities || [], null, 2);
    },
    realLogicEntityCount() {
      return Array.isArray(this.card.logicEntities) ? this.card.logicEntities.length : 0;
    },
    isMobile() {
      return this.viewportWidth <= 768 || (this.viewportWidth <= 900 && this.isPortrait);
    },
    isPortrait() {
      return this.viewportHeight >= this.viewportWidth;
    },
    selectedTreeNodeLabel() {
      if (!this.selectedSkillTreeNode) return '未选中节点';
      return this.logicLocalization.node_names?.[this.selectedSkillTreeNode.node_id] || this.selectedSkillTreeNode.node_id;
    },
    inspectorFields() {
      void this.logicTreeRevision;
      return getInspectorFields(this.selectedSkillTreeNode, this.nodeDef, this.logicLocalization);
    },
    replaceCandidates() {
      if (!this.selectedSkillTreeNode) return [];
      return collectReplaceCandidates(this.selectedSkillTreeNode.node_id, this.nodeDef, this.logicLocalization);
    },
    canLogicUndo() {
      return canUndo(this.logicHistory);
    },
    canLogicRedo() {
      return canRedo(this.logicHistory);
    },
    logicDescPreview() {
      const entities = this.card.logicEntities || [];
      if (!entities.length) return '暂无技能。请在工作区搭建结构树，或导入含技能的卡牌 JSON。';
      const parts = [];
      for (let i = 0; i < entities.length; i += 1) {
        const comps = (entities[i]?.components || []).map(c => {
          const t = String(c?.$type || '');
          return t.split('.').pop()?.split(',')[0]?.replace('Descriptor', '').replace('Effect', '') || 'Component';
        });
        parts.push(`技能组 ${i + 1}：${comps.join(' → ')}`);
      }
      return parts.join('\n');
    },
    cardDisplayTitle() {
      return this.cardIndexInfo?.NAME_CN || this.card.name || (this.card.guid ? `卡牌 ${this.card.guid}` : '未命名卡牌');
    }
  },
  watch: {
    card: {
      deep: true,
      handler(value) { saveCard(value); }
    },
    'card.logicSubtypes'(value) {
      this.card.displaySubtypes = [...value];
    },
    'card.logicTagsText'(value) {
      this.card.displayTagsText = value;
    },
    filteredPalette: {
      immediate: true,
      handler(groups) {
        if (!groups?.length) return;
        const next = { ...this.expandedPaletteGroups };
        let changed = false;
        for (const g of groups) {
          if (next[g.id] === undefined) {
            next[g.id] = Object.keys(next).length < 2;
            changed = true;
          }
        }
        if (changed) this.expandedPaletteGroups = next;
      }
    }
  },
  async mounted() {
    this.applyViewportMode();
    this._onViewportResize = () => this.applyViewportMode();
    window.addEventListener('resize', this._onViewportResize, { passive: true });
    window.addEventListener('orientationchange', this._onViewportResize, { passive: true });

    try { await pingPhantom(); } catch (error) { console.warn(error.message); }

    try {
      const config = await loadPhantomConfig();
      this.phantomConfig = {
        ...this.phantomConfig,
        loaded: true,
        version: config.version,
        stage: config.stage,
        nodeDef: config.node_def || {},
        localization: config.localization || emptyConfig.localization,
        palette: config.palette || [],
        userPresets: config.user_presets || {},
        skillLibrary: config.skill_library || { categories: [], total_nodes: 0 },
        cardIndex: Array.isArray(config.card_index) ? config.card_index : [],
        cardIndexMeta: config.card_index_meta || { source: '', count: 0, loaded: false, error: '' },
        enums: config.enums || fallbackOptions
      };
      this.options = { ...fallbackOptions, ...this.phantomConfig.enums };
      const paletteReady = (this.phantomConfig.palette || []).length > 0;
      const nodeDefReady = Object.keys(this.phantomConfig.nodeDef || {}).length > 0;
      this.configStatus = paletteReady && nodeDefReady ? 'loaded' : 'fallback';
      if (!paletteReady || !nodeDefReady) {
        console.warn('组件库或节点定义未就绪，请检查 /api/phantom/config 与静态兜底配置。');
      }
    } catch (error) {
      this.configStatus = 'fallback';
      console.warn(error.message);
    }

    this.card.skillTreeDraft = normalizeLogicTreeDraft(this.card.skillTreeDraft);
    this.card = this.prepareImportedCard(this.card);
    this.reloadLogicTree(true);
    this.bumpLogicTree();
  },
  beforeUnmount() {
    if (this._onViewportResize) {
      window.removeEventListener('resize', this._onViewportResize);
      window.removeEventListener('orientationchange', this._onViewportResize);
    }
    if (this.toastTimer) clearTimeout(this.toastTimer);
  },
  methods: {
    labelOf,
    formatEnumLabel,
    bumpLogicTree() {
      this.logicTreeRevision += 1;
    },
    applyViewportMode() {
      this.viewportWidth = window.innerWidth;
      this.viewportHeight = window.innerHeight;
    },
    setActiveTab(tabId) {
      this.activeTab = tabId;
      this.mobileMenuOpen = false;
      if (this.isMobile) window.scrollTo({ top: 0, behavior: 'smooth' });
    },
    setLogicWorkspace(id) { this.logicWorkspace = id; },
    openMobileMenu() { this.mobileMenuOpen = true; },
    closeMobileSheets() { this.mobileMenuOpen = false; },
    showToast(message) {
      this.toastMessage = message;
      if (this.toastTimer) clearTimeout(this.toastTimer);
      this.toastTimer = setTimeout(() => {
        this.toastMessage = '';
        this.toastTimer = null;
      }, 2200);
    },
    isPaletteGroupExpanded(groupId) {
      return !!this.expandedPaletteGroups[groupId];
    },
    togglePaletteGroup(groupId) {
      this.expandedPaletteGroups = {
        ...this.expandedPaletteGroups,
        [groupId]: !this.expandedPaletteGroups[groupId]
      };
    },
    normalizeIndexText(value) {
      const text = String(value ?? '').trim();
      if (/^\d+$/.test(text)) return String(Number(text));
      return text.toLowerCase();
    },
    findCardIndexInfo(card) {
      const list = this.phantomConfig.cardIndex || [];
      if (!card || !list.length) return null;
      const guid = this.normalizeIndexText(card.guid);
      if (!guid) return null;
      return list.find(item => this.normalizeIndexText(item.GUID) === guid) || null;
    },
    syncCardFromIndex() {
      const info = this.findCardIndexInfo(this.card);
      if (!info) {
        this.showToast('未匹配到 GUID 索引');
        return;
      }
      this.card.name = info.NAME_CN || this.card.name;
      this.card.prefabName = info.UUID || this.card.prefabName;
      this.showToast('已同步名称与 UUID');
    },
    resetCard() {
      if (!confirm('清空本地草稿并重新开始？')) return;
      clearCardStorage();
      this.card = createEmptyCard();
      this.reloadLogicTree(true);
      this.setActiveTab('basic');
      this.showToast('已重置草稿');
    },
    prepareImportedCard(card) {
      const merged = { ...createEmptyCard(), ...card, localId: card.localId || createEmptyCard().localId };
      const info = this.findCardIndexInfo(merged);
      if (info) {
        if (info.NAME_CN) merged.name = info.NAME_CN;
        if (info.UUID) merged.prefabName = info.UUID;
      }
      const originalEntities = JSON.parse(JSON.stringify(merged.logicEntities || []));
      merged.skillTreeDraft = migrateLegacyTreeDraft(merged.skillTreeDraft, originalEntities, this.nodeDef);
      if (!treeHasContent(merged.skillTreeDraft.roots) && originalEntities.length) {
        merged.skillTreeDraft = buildTreeFromLogicEntities(originalEntities, this.nodeDef);
      }
      const parsed = parseTreeToLogicEntities(merged.skillTreeDraft.roots, this.nodeDef);
      merged.logicEntities = parsed.length ? parsed : originalEntities;
      return merged;
    },
    reloadLogicTree(forceFromEntities = false) {
      const originalEntities = JSON.parse(JSON.stringify(this.card.logicEntities || []));
      if (forceFromEntities && originalEntities.length) {
        this.card.skillTreeDraft = buildTreeFromLogicEntities(originalEntities, this.nodeDef);
      } else {
        this.card.skillTreeDraft = migrateLegacyTreeDraft(
          this.card.skillTreeDraft,
          originalEntities,
          this.nodeDef
        );
      }
      if (treeHasContent(this.card.skillTreeDraft.roots)) {
        this.syncLogicEntitiesFromTree({ recordHistory: true, resetHistory: true });
      } else {
        clearHistory(this.logicHistory);
        this.card.logicEntities = originalEntities;
      }
      this.selectedSkillTreeNodeUid = this.skillTreeDraft.roots[0]?.uid || '';
      this.bumpLogicTree();
    },
    syncLogicEntitiesFromTree({ recordHistory = true, resetHistory = false } = {}) {
      if (this._syncingLogic) return;
      this._syncingLogic = true;
      try {
        const roots = this.skillTreeDraft.roots || [];
        if (treeHasContent(roots)) {
          this.card.logicEntities = parseTreeToLogicEntities(roots, this.nodeDef);
        }
        if (resetHistory) {
          clearHistory(this.logicHistory);
          saveHistorySnapshot(this.logicHistory, roots);
        } else if (recordHistory) {
          saveHistorySnapshot(this.logicHistory, roots);
        }
      } finally {
        this._syncingLogic = false;
      }
    },
    onLogicTreeChanged() {
      this.syncLogicEntitiesFromTree({ recordHistory: true });
      this.bumpLogicTree();
    },
    exportCardJson() {
      const guid = this.card.guid || 'card';
      downloadJson(`${guid}.json`, this.gameCardJson);
      this.showToast('已下载卡牌 JSON');
    },
    async importCardJsonFile(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file) return;
      try {
        const data = await readJsonFile(file);
        const { guid, entry } = extractEntryFromImportedJson(data, this.importGuid || this.card.guid);
        const imported = cardFormFromGameEntry(guid, entry, createEmptyCard, this.phantomConfig);
        imported.localId = this.card.localId;
        this.card = this.prepareImportedCard(imported);
        this.importGuid = String(guid);
        this.reloadLogicTree(true);
        this.setActiveTab('basic');
        this.showToast(`已导入卡牌 ${guid}`);
      } catch (error) {
        this.showToast(`导入失败：${error.message}`);
      }
    },
    applyCardTypeDefaults() {
      const baseId = this.card.baseId || '';
      const faction = this.card.faction || '';
      const isBoardTemplate = baseId === 'BoardAbility';
      const isTrick = baseId.includes('OneTimeEffect') && !isBoardTemplate;
      const isEnv = baseId.includes('Environment');
      const isFighter = !isTrick && !isEnv && !isBoardTemplate;
      const isZombie = faction === 'Zombies';
      this.card.hasAttack = isFighter;
      this.card.hasHealth = isFighter;
      const flags = new Set(this.card.flags || []);
      const setFlag = (name, enabled) => enabled ? flags.add(name) : flags.delete(name);
      setFlag('IsTrick', isTrick);
      setFlag('IsEnvironment', isEnv);
      setFlag('IsSurprise', isZombie && (isTrick || isEnv));
      setFlag('IsBoardAbility', isBoardTemplate);
      this.card.flags = [...flags];
      this.showToast('已同步类型默认值');
    },
    removeSpecialAbility(id) {
      this.card.specialAbilities = (this.card.specialAbilities || []).filter(item => item !== id);
    },
    clearSpecialAbilities() {
      if (!confirm('清空所有基础特殊能力？')) return;
      this.card.specialAbilities = [];
    },
    clearRootAbilities() {
      if (!confirm('清空根目录特殊能力？')) return;
      this.card.rootSpecialAbilities = [];
    },
    addTriggeredPreset() {
      const preset = this.triggeredAbilityPresets.find(item => item.id === this.newTriggeredAbilityType);
      if (!preset) return;
      if (preset.id === 'Custom') {
        const g = Number(this.customTriggeredAbility.g);
        if (!Number.isFinite(g) || g <= 0) {
          this.showToast('自定义 g 必须大于 0');
          return;
        }
        this.card.triggeredAbilities.push({
          g,
          vt: Number(this.customTriggeredAbility.vt) || 0,
          va: Number(this.customTriggeredAbility.va) || 0
        });
        this.customTriggeredAbility = { g: 0, vt: 0, va: 0 };
        return;
      }
      this.card.triggeredAbilities.push(JSON.parse(JSON.stringify(preset.data)));
    },
    removeTriggeredAbility(index) {
      this.card.triggeredAbilities.splice(index, 1);
    },
    describeTriggeredAbility(item) {
      if (!item || typeof item !== 'object') return '未知触发能力';
      if (Number(item.g) === 562) return '💥 双重攻击';
      if (Number(item.g) === 564) return '🎯 先攻';
      return `🧩 g=${item.g ?? '-'} vt=${item.vt ?? '-'} va=${item.va ?? '-'}`;
    },
    addSubtype() {
      if (!this.newSubtype.id || !this.newSubtype.name) return;
      this.options.subtypes.push({
        id: Number(this.newSubtype.id),
        value: Number(this.newSubtype.id),
        name: this.newSubtype.name
      });
      this.newSubtype = { id: '', name: '' };
      this.showToast('种族已加入本地列表');
    },
    selectPaletteItem(item) { this.selectedPaletteItem = item; },
    selectSkillTreeNode(uid) {
      this.selectedSkillTreeNodeUid = uid;
      this.showReplaceMenu = false;
      if (this.isMobile) this.logicWorkspace = 'inspector';
    },
    findInsertParentUid(childNodeId) {
      if (!this.selectedSkillTreeNodeUid) return null;
      let uid = this.selectedSkillTreeNodeUid;
      while (uid) {
        const { node, parent } = findNodeAndParent(this.skillTreeDraft.roots, uid);
        if (!node) break;
        if (canInsertNode(node.node_id, childNodeId, this.nodeDef)) return node.uid;
        uid = parent?.uid || null;
      }
      return null;
    },
    addFromPalette(asRoot = false) {
      const item = this.selectedPaletteItem;
      if (!item) {
        this.showToast('请先在组件库选择一个节点');
        this.logicWorkspace = 'library';
        return;
      }
      if (item.kind === 'preset' || item.isPreset) {
        const preset = this.phantomConfig.userPresets?.[item.id];
        if (!preset) { this.showToast('预设不存在'); return; }
        const restored = restoreNodeFromSnapshot(preset, this.nodeDef);
        if (preset.node_id === 'AbilityGroup' || asRoot) {
          this.skillTreeDraft.roots.push(restored);
          this.selectedSkillTreeNodeUid = restored.uid;
        } else {
          const parentUid = this.findInsertParentUid(preset.node_id);
          if (!parentUid) { this.showToast('当前选中位置无法插入该预设'); return; }
          const result = addChildNode(this.skillTreeDraft.roots, parentUid, restored, this.nodeDef);
          if (!result.ok) { this.showToast(result.error || '插入失败'); return; }
          this.selectedSkillTreeNodeUid = restored.uid;
        }
      } else {
        const node = createNodeFromDef(item.id, this.nodeDef[item.id] || {});
        if (asRoot && node.node_id !== 'AbilityGroup') {
          this.showToast('除技能组外，请选中父节点后插入');
          return;
        }
        const parentUid = asRoot ? null : this.findInsertParentUid(item.id);
        if (!asRoot && !parentUid) {
          this.showToast('请在工作区选中合法的父节点');
          return;
        }
        const result = addChildNode(this.skillTreeDraft.roots, parentUid, node, this.nodeDef);
        if (!result.ok) { this.showToast(result.error || '插入失败'); return; }
        this.selectedSkillTreeNodeUid = node.uid;
      }
      this.onLogicTreeChanged();
      this.logicWorkspace = 'tree';
      this.showToast('已添加节点');
    },
    addAbilityGroup() {
      const group = addAbilityGroup(this.skillTreeDraft.roots, this.nodeDef);
      this.selectedSkillTreeNodeUid = group.uid;
      this.onLogicTreeChanged();
      this.logicWorkspace = 'tree';
      this.showToast('已新建技能组');
    },
    removeSelectedSkillTreeNode() {
      if (!this.selectedSkillTreeNodeUid) return;
      if (!confirm('删除该节点及所有子节点？')) return;
      if (!removeTreeNode(this.skillTreeDraft.roots, this.selectedSkillTreeNodeUid)) {
        this.showToast('该节点不可删除');
        return;
      }
      this.selectedSkillTreeNodeUid = '';
      this.onLogicTreeChanged();
    },
    moveSelectedSkillTreeNode(direction) {
      if (!this.selectedSkillTreeNodeUid) return;
      moveTreeNode(this.skillTreeDraft.roots, this.selectedSkillTreeNodeUid, direction);
      this.onLogicTreeChanged();
    },
    duplicateSelectedSkillTreeNode() {
      if (!this.selectedSkillTreeNodeUid) return;
      const cloned = duplicateTreeNode(this.skillTreeDraft.roots, this.selectedSkillTreeNodeUid);
      if (cloned) {
        this.selectedSkillTreeNodeUid = cloned.uid;
        this.onLogicTreeChanged();
      }
    },
    toggleSelectedSkillTreeNodeDisabled() {
      if (!this.selectedSkillTreeNode) return;
      this.selectedSkillTreeNode.disabled = !this.selectedSkillTreeNode.disabled;
      const toggleChildren = (node, state) => {
        (node.children || []).forEach(child => {
          child.disabled = state;
          toggleChildren(child, state);
        });
      };
      toggleChildren(this.selectedSkillTreeNode, this.selectedSkillTreeNode.disabled);
      this.onLogicTreeChanged();
    },
    toggleSkillTreeNodeCollapsed(row) {
      if (!row?.node) return;
      row.node.collapsed = !row.node.collapsed;
    },
    expandAllSkillTree() {
      const walk = (nodes) => {
        for (const n of nodes || []) { n.collapsed = false; walk(n.children); }
      };
      walk(this.skillTreeDraft.roots);
    },
    collapseAllSkillTree() {
      const walk = (nodes) => {
        for (const n of nodes || []) { n.collapsed = true; walk(n.children); }
      };
      walk(this.skillTreeDraft.roots);
    },
    clearSkillTreeDraft() {
      if (!confirm('清空技能结构树？')) return;
      this.card.skillTreeDraft = normalizeLogicTreeDraft({ roots: [] });
      this.selectedSkillTreeNodeUid = '';
      this.onLogicTreeChanged();
      this.showToast('结构树已清空');
    },
    refreshTreeFromRealLogic() {
      if (!this.realLogicEntityCount) {
        this.showToast('当前卡牌没有可读取的技能');
        return;
      }
      if (this.skillTreeDraft.roots.length && !confirm('用卡牌现有技能覆盖结构树？')) return;
      this.reloadLogicTree(true);
      this.logicWorkspace = 'tree';
      this.showToast('已从卡牌读取技能结构');
    },
    insertSkillTemplate(templateId) {
      const template = this.skillTemplatePresets.find(item => item.id === templateId);
      if (!template) return;
      const draft = createSkillTemplateTree(templateId, this.nodeDef);
      if (this.skillTreeDraft.roots.length && !confirm(`追加模板「${template.name}」？`)) return;
      this.skillTreeDraft.roots.push(...draft.roots);
      this.selectedSkillTreeNodeUid = draft.roots[0]?.uid || this.selectedSkillTreeNodeUid;
      this.onLogicTreeChanged();
      this.logicWorkspace = 'tree';
      this.showToast(`已插入模板：${template.name}`);
    },
    updateInspectorParam(key, value) {
      if (!this.selectedSkillTreeNode) return;
      onParamUpdated(this.selectedSkillTreeNode, key, value, this.nodeDef);
      this.onLogicTreeChanged();
    },
    replaceSelectedNode(newNodeId) {
      if (!this.selectedSkillTreeNode) return;
      replaceTreeNode(this.selectedSkillTreeNode, newNodeId, this.nodeDef);
      this.showReplaceMenu = false;
      this.onLogicTreeChanged();
      this.showToast('已更换节点');
    },
    logicUndo() {
      const restored = undoHistory(this.logicHistory);
      if (!restored) return;
      this.card.skillTreeDraft = {
        ...this.skillTreeDraft,
        roots: restored
      };
      this.syncLogicEntitiesFromTree({ recordHistory: false });
      this.bumpLogicTree();
    },
    logicRedo() {
      const restored = redoHistory(this.logicHistory);
      if (!restored) return;
      this.card.skillTreeDraft = {
        ...this.skillTreeDraft,
        roots: restored
      };
      this.syncLogicEntitiesFromTree({ recordHistory: false });
      this.bumpLogicTree();
    },
    treeNodeSummary(node) {
      return treeNodeSummary(node, this.logicLocalization, this.nodeDef);
    },
    nodeHasChildrenHint(nodeId) {
      const defn = this.nodeDef[nodeId] || {};
      return !!(defn.allowed_children?.length || ['AdditionalTargetQuery', 'FinderPlaceholder', 'QueryPlaceholder'].includes(nodeId));
    },
    async copyPreview() {
      try {
        await navigator.clipboard.writeText(this.previewJson);
        this.showToast('已复制卡牌 JSON');
      } catch (_) {
        this.showToast('复制失败');
      }
    },
    async copySkillJson() {
      try {
        await navigator.clipboard.writeText(this.realLogicEntitiesJson);
        this.showToast('已复制技能 JSON');
      } catch (_) {
        this.showToast('复制失败');
      }
    }
  }
}).mount('#phantom-app');