import { tabs, fallbackOptions, emptyConfig, createEmptyCard, createDefaultProject } from './state.js';
import { loadProject, saveProject as persistProject, downloadJson, downloadBlob, readJsonFile } from './project.js';
import { pingPhantom, loadPhantomConfig, validatePhantomProject, inspectPhantomBundle, diffPhantomCards, packPhantomBundle } from './api.js';
import { createTranslator, labelOf } from './i18n.js';
import { filterSkillCategories } from './skill_library.js';
import { normalizeSkillTreeDraft, createTreeNodeFromLibraryNode, flattenSkillTree, findNodeAndParent, addChildNode, removeTreeNode, moveTreeNode, duplicateTreeNode, treeNodeSummary, buildTreeFromRealLogicEntities, buildSkillTreeSource } from './skill_tree.js';
import { generateGameCardEntry, generateProjectCardsJson, cardFormFromGameEntry, extractEntryFromImportedJson } from './card_serializer.js';

const { createApp } = Vue;

createApp({
  delimiters: ['[[', ']]'],
  data() {
    const project = loadProject();
    return {
      tabs,
      options: { ...fallbackOptions },
      phantomConfig: { ...emptyConfig },
      project,
      activeTab: 'project',
      currentCardId: project.cards[0]?.localId || null,
      newSubtype: { id: '', name: '' },
      newGrantedAbility: '',
      abilitySearch: '',
      newTriggeredAbilityType: 'DoubleStrike',
      customTriggeredAbility: { g: 0, vt: 0, va: 0 },
      exportName: 'card_data_1',
      bundleTargetAssetName: 'cards',
      bundleOutputName: 'card_data_1',
      selectedBundleFile: null,
      packStatus: '',
      packBusy: false,
      validateBusy: false,
      inspectBusy: false,
      diffBusy: false,
      validationResult: null,
      bundleInspectResult: null,
      diffResult: null,
      selectedDiffJsonFile: null,
      selectedDiffJsonName: '',
      originalDiffJson: null,
      importGuid: '',
      skillSearch: '',
      selectedSkillNode: null,
      activeLogicMode: 'tree_editor',
      realLogicViewMode: 'tree',
      selectedSkillTreeNodeUid: '',
      settings: {
        syncSubtypes: true,
        syncTags: true,
        compactMode: false,
        showPreview: true,
        mobilePreviewMode: true,
        language: 'zh-CN',
        font: 'system-ui'
      },
      apiReady: false,
      configStatus: 'loading'
    };
  },
  computed: {
    t() {
      return createTranslator({ ...this.phantomConfig, language: this.settings.language });
    },
    currentTab() {
      return this.tabs.find(tab => tab.id === this.activeTab) || this.tabs[0];
    },
    currentCard() {
      if (!this.project.cards.length) {
        const card = createEmptyCard();
        this.project.cards.push(card);
        this.currentCardId = card.localId;
      }
      return this.project.cards.find(card => card.localId === this.currentCardId) || this.project.cards[0];
    },
    skillCategories() {
      return filterSkillCategories(this.phantomConfig.skillLibrary, this.skillSearch);
    },
    triggerSkillNodes() {
      const category = (this.phantomConfig.skillLibrary?.categories || []).find(item => item.id === 'Trigger');
      return category?.nodes || [];
    },
    configSummary() {
      return {
        version: this.phantomConfig.version,
        stage: this.phantomConfig.stage,
        fonts: this.phantomConfig.fonts.length,
        skill_nodes: this.phantomConfig.skillLibrary?.total_nodes || 0,
        skill_categories: this.phantomConfig.skillLibrary?.categories?.length || 0,
        languages: this.phantomConfig.supportedLanguages
      };
    },
    currentGameCardJson() {
      return generateGameCardEntry(this.currentCard, this.phantomConfig);
    },
    projectGameCardsJson() {
      return generateProjectCardsJson(this.project, this.phantomConfig);
    },
    previewJson() {
      return JSON.stringify(this.currentGameCardJson, null, 2);
    },
    projectPreviewJson() {
      return JSON.stringify(this.projectGameCardsJson, null, 2);
    },
    diffSummary() {
      return this.diffResult?.diff?.summary || { original_count: 0, modded_count: 0, added: 0, removed: 0, changed: 0 };
    },
    filteredSpecialAbilities() {
      const q = (this.abilitySearch || '').toLowerCase().trim();
      const list = this.options.specialAbilities || [];
      if (!q) return list;
      return list.filter(item => `${item.id} ${item.name} ${item.type || ''}`.toLowerCase().includes(q));
    },
    selectedSpecialAbilityDetails() {
      const selected = new Set(this.currentCard.specialAbilities || []);
      return (this.options.specialAbilities || []).filter(item => selected.has(item.id));
    },
    abilityOptionMap() {
      const map = {};
      for (const ability of this.options.specialAbilities || []) map[ability.id] = ability;
      return map;
    },
    triggeredAbilityPresets() {
      return [
        { id: 'DoubleStrike', name: '💥 双重攻击', data: { g: 562, vt: 0, va: 0 } },
        { id: 'Overshoot', name: '🎯 先攻', data: { g: 564, vt: 1, va: 2 } },
        { id: 'Custom', name: '🧩 自定义能力', data: null }
      ];
    },
    filteredSkillCategories() {
      return this.skillCategories || [];
    },
    currentSkillTreeDraft() {
      const normalized = normalizeSkillTreeDraft(this.currentCard.skillTreeDraft);
      if (this.currentCard.skillTreeDraft !== normalized) this.currentCard.skillTreeDraft = normalized;
      return this.currentCard.skillTreeDraft;
    },
    skillTreeRows() {
      return flattenSkillTree(this.currentSkillTreeDraft.roots || []);
    },
    selectedSkillTreeNode() {
      return findNodeAndParent(this.currentSkillTreeDraft.roots || [], this.selectedSkillTreeNodeUid).node;
    },
    selectedSkillTreeNodeJson() {
      return this.selectedSkillTreeNode ? JSON.stringify(this.selectedSkillTreeNode, null, 2) : '';
    },
    skillTreeDraftJson() {
      return JSON.stringify(buildSkillTreeSource(this.currentSkillTreeDraft), null, 2);
    },
    realLogicEntityTree() {
      return buildTreeFromRealLogicEntities(this.currentCard.logicEntities || []);
    },
    realLogicEntityTreeJson() {
      return JSON.stringify(this.realLogicEntityTree, null, 2);
    },
    realLogicEntitiesJson() {
      return JSON.stringify(this.currentCard.logicEntities || [], null, 2);
    },
    realLogicEntityCount() {
      return Array.isArray(this.currentCard.logicEntities) ? this.currentCard.logicEntities.length : 0;
    }
  },
  watch: {
    project: {
      deep: true,
      handler(value) { persistProject(value); }
    },
    'currentCard.logicSubtypes'(value) {
      if (this.settings.syncSubtypes) this.currentCard.displaySubtypes = [...value];
    },
    'currentCard.logicTagsText'(value) {
      if (this.settings.syncTags) this.currentCard.displayTagsText = value;
    }
  },
  async mounted() {
    try {
      const result = await pingPhantom();
      this.apiReady = !!result.ok;
    } catch (error) {
      console.warn(error.message);
    }

    try {
      const config = await loadPhantomConfig();
      this.phantomConfig = {
        ...this.phantomConfig,
        loaded: true,
        version: config.version,
        stage: config.stage,
        defaultFont: config.default_font || 'system-ui',
        supportedLanguages: config.supported_languages || ['zh-CN'],
        fonts: config.fonts || [],
        localization: config.localization || { 'zh-CN': {} },
        skillLibrary: config.skill_library || { categories: [], total_nodes: 0 },
        enums: config.enums || fallbackOptions,
        notes: config.notes || []
      };
      this.options = { ...fallbackOptions, ...this.phantomConfig.enums };
      this.settings.language = config.default_language || 'zh-CN';
      this.settings.font = config.default_font || 'system-ui';
      this.configStatus = 'loaded';
    } catch (error) {
      this.configStatus = 'fallback';
      console.warn(error.message);
    }
  },
  methods: {
    labelOf,
    newProject() {
      if (!confirm('新建工程会覆盖当前浏览器本地工程，确定继续？')) return;
      this.project = createDefaultProject();
      this.currentCardId = this.project.cards[0].localId;
      this.activeTab = 'project';
    },
    saveProject() { this.project = persistProject(this.project); },
    newCard() {
      const card = createEmptyCard();
      card.name = `自定义卡牌 ${this.project.cards.length + 1}`;
      this.project.cards.push(card);
      this.currentCardId = card.localId;
      this.activeTab = 'basic';
    },
    selectCard(localId) {
      this.currentCardId = localId;
      this.activeTab = 'basic';
    },
    removeCard(localId) {
      if (!confirm('确定从当前工程移除这张卡牌？')) return;
      this.project.cards = this.project.cards.filter(card => card.localId !== localId);
      this.currentCardId = this.project.cards[0]?.localId || null;
    },
    exportProject() {
      const safeName = (this.project.name || 'phantom_project').replace(/[\/:*?"<>|\s]+/g, '_');
      downloadJson(`${safeName}.phantom`, this.project);
    },
    exportGeneratedCardJson() {
      const guid = this.currentCard.guid || 'current_card';
      downloadJson(`${guid}.card.json`, this.currentGameCardJson);
    },
    exportGeneratedProjectJson() {
      const safeName = (this.exportName || 'card_data_1').replace(/[\/:*?"<>|\s]+/g, '_');
      downloadJson(`${safeName}.json`, this.projectGameCardsJson);
    },
    normalizeProject(data) {
      const project = {
        name: data.name || '导入的 Phantom 工程',
        version: data.version || '0.9-field-ability-complete',
        cards: Array.isArray(data.cards) ? data.cards : [],
        updatedAt: data.updatedAt || new Date().toISOString()
      };
      project.cards = project.cards.map(card => {
        const merged = { ...createEmptyCard(), ...card, localId: card.localId || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now() + Math.random())) };
        merged.skillTreeDraft = normalizeSkillTreeDraft(merged.skillTreeDraft);
        return merged;
      });
      if (!project.cards.length) project.cards.push(createEmptyCard());
      return project;
    },
    async importCardJsonFile(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file) return;
      try {
        const data = await readJsonFile(file);
        const { guid, entry } = extractEntryFromImportedJson(data, this.importGuid || this.currentCard.guid);
        const imported = cardFormFromGameEntry(guid, entry, createEmptyCard, this.config);
        imported.localId = this.currentCard?.localId || imported.localId;
        const index = this.project.cards.findIndex(card => card.localId === this.currentCardId);
        if (index >= 0) this.project.cards.splice(index, 1, imported);
        else this.project.cards.push(imported);
        this.currentCardId = imported.localId;
        this.importGuid = String(guid);
        this.activeTab = 'basic';
      } catch (error) {
        alert(`卡牌导入失败：${error.message}`);
      }
    },
    async importCardsAsProject(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file) return;
      try {
        const data = await readJsonFile(file);
        const keys = Object.keys(data || {}).filter(key => data[key]?.entity?.components);
        if (!keys.length) throw new Error('未检测到 card_data 格式的卡牌条目');
        const cards = keys.map(key => cardFormFromGameEntry(key, data[key], createEmptyCard, this.config));
        this.project = { name: file.name.replace(/\.json$/i, ''), version: '0.9-imported-card-data', cards: cards.map(card => ({ ...card, skillTreeDraft: normalizeSkillTreeDraft(card.skillTreeDraft) })), updatedAt: new Date().toISOString() };
        this.currentCardId = cards[0]?.localId || null;
        this.activeTab = 'project';
      } catch (error) {
        alert(`批量导入失败：${error.message}`);
      }
    },
    async importProjectFile(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      if (!file) return;
      try {
        const data = await readJsonFile(file);
        if (!data.cards || !Array.isArray(data.cards)) throw new Error('工程文件缺少 cards 数组');
        this.project = this.normalizeProject(data);
        this.currentCardId = this.project.cards[0]?.localId || null;
        this.activeTab = 'project';
      } catch (error) {
        alert(`导入失败：${error.message}`);
      }
    },
    selectBundleFile(event) {
      this.selectedBundleFile = event.target.files?.[0] || null;
      this.packStatus = this.selectedBundleFile ? `已选择：${this.selectedBundleFile.name}` : '';
      this.bundleInspectResult = null;
    },
    async validateCurrentProject() {
      if (this.validateBusy) return;
      try {
        this.validateBusy = true;
        this.validationResult = await validatePhantomProject(this.projectGameCardsJson);
      } catch (error) {
        this.validationResult = { ok: false, message: error.message, summary: { cards: 0, errors: 1, warnings: 0 }, errors: [{ guid: '-', field: 'validate', message: error.message }], warnings: [] };
      } finally {
        this.validateBusy = false;
      }
    },
    async inspectSelectedBundle() {
      if (this.inspectBusy) return;
      try {
        this.inspectBusy = true;
        this.bundleInspectResult = await inspectPhantomBundle({ bundleFile: this.selectedBundleFile, targetAssetName: this.bundleTargetAssetName });
      } catch (error) {
        this.bundleInspectResult = { ok: false, message: error.message, detail: { resources: [] } };
      } finally {
        this.inspectBusy = false;
      }
    },
    async selectDiffJsonFile(event) {
      const file = event.target.files?.[0];
      event.target.value = '';
      this.selectedDiffJsonFile = file || null;
      this.selectedDiffJsonName = file?.name || '';
      this.originalDiffJson = null;
      if (!file) return;
      try {
        this.originalDiffJson = await readJsonFile(file);
      } catch (error) {
        this.selectedDiffJsonName = '';
        alert(`原始 JSON 读取失败：${error.message}`);
      }
    },
    async runDiffPreview() {
      if (this.diffBusy) return;
      try {
        this.diffBusy = true;
        this.diffResult = await diffPhantomCards({
          cardsJson: this.projectGameCardsJson,
          originalJson: this.originalDiffJson,
          bundleFile: this.originalDiffJson ? null : this.selectedBundleFile,
          targetAssetName: this.bundleTargetAssetName
        });
      } catch (error) {
        this.diffResult = { ok: false, message: error.message, diff: { summary: { original_count: 0, modded_count: 0, added: 0, removed: 0, changed: 0 }, added_cards: [], removed_cards: [], changed_cards: [] } };
      } finally {
        this.diffBusy = false;
      }
    },
    async packCurrentProjectToBundle() {
      if (this.packBusy) return;
      try {
        this.packBusy = true;
        this.packStatus = '正在校验工程……';
        const validation = await validatePhantomProject(this.projectGameCardsJson);
        this.validationResult = validation;
        if (!validation.ok) throw new Error('工程校验未通过，请先处理错误后再打包。');
        this.packStatus = '正在注入并打包，请不要关闭页面……';
        const { blob, filename } = await packPhantomBundle({
          bundleFile: this.selectedBundleFile,
          cardsJson: this.projectGameCardsJson,
          targetAssetName: this.bundleTargetAssetName,
          outputName: this.bundleOutputName || this.exportName || 'card_data_1'
        });
        downloadBlob(filename, blob);
        this.packStatus = `打包完成：${filename}`;
      } catch (error) {
        this.packStatus = `打包失败：${error.message}`;
        alert(this.packStatus);
      } finally {
        this.packBusy = false;
      }
    },
    applyCardTypeDefaults() {
      const baseId = this.currentCard.baseId || '';
      const faction = this.currentCard.faction || '';
      const isBoardTemplate = baseId === 'BoardAbility';
      const isTrick = baseId.includes('OneTimeEffect') && !isBoardTemplate;
      const isEnv = baseId.includes('Environment');
      const isFighter = !isTrick && !isEnv && !isBoardTemplate;
      const isZombie = faction === 'Zombies';
      this.currentCard.hasAttack = isFighter;
      this.currentCard.hasHealth = isFighter;
      const flags = new Set(this.currentCard.flags || []);
      const setFlag = (name, enabled) => enabled ? flags.add(name) : flags.delete(name);
      setFlag('IsTrick', isTrick);
      setFlag('IsEnvironment', isEnv);
      setFlag('IsSurprise', isZombie && (isTrick || isEnv));
      setFlag('IsBoardAbility', isBoardTemplate);
      this.currentCard.flags = [...flags];
    },
    abilityOptionById(id) {
      return this.abilityOptionMap[id] || { id, name: id, type: 'unknown' };
    },
    removeSpecialAbility(id) {
      this.currentCard.specialAbilities = (this.currentCard.specialAbilities || []).filter(item => item !== id);
    },
    clearSpecialAbilities() {
      if (!confirm('确定清空所有基础特殊能力？')) return;
      this.currentCard.specialAbilities = [];
    },
    clearRootAbilities() {
      if (!confirm('确定清空所有根目录特殊能力？')) return;
      this.currentCard.rootSpecialAbilities = [];
    },
    addTriggeredPreset() {
      const preset = this.triggeredAbilityPresets.find(item => item.id === this.newTriggeredAbilityType);
      if (!preset) return;
      if (preset.id === 'Custom') {
        this.addCustomTriggeredAbility();
        return;
      }
      this.currentCard.triggeredAbilities.push(JSON.parse(JSON.stringify(preset.data)));
    },
    addCustomTriggeredAbility() {
      const g = Number(this.customTriggeredAbility.g);
      const vt = Number(this.customTriggeredAbility.vt);
      const va = Number(this.customTriggeredAbility.va);
      if (!Number.isFinite(g) || g <= 0) {
        alert('自定义能力 ID(g) 必须是大于 0 的数字。');
        return;
      }
      this.currentCard.triggeredAbilities.push({ g, vt: Number.isFinite(vt) ? vt : 0, va: Number.isFinite(va) ? va : 0 });
      this.customTriggeredAbility = { g: 0, vt: 0, va: 0 };
    },
    removeTriggeredAbility(index) {
      this.currentCard.triggeredAbilities.splice(index, 1);
    },
    describeTriggeredAbility(item) {
      if (!item || typeof item !== 'object') return '未知触发能力';
      if (Number(item.g) === 562) return '💥 双重攻击';
      if (Number(item.g) === 564) return '🎯 先攻 / Overshoot';
      return `🧩 自定义能力 g=${item.g ?? '-'} vt=${item.vt ?? '-'} va=${item.va ?? '-'}`;
    },
    addSubtype() {
      if (!this.newSubtype.id || !this.newSubtype.name) return;
      this.options.subtypes.push({ id: Number(this.newSubtype.id), value: Number(this.newSubtype.id), name: this.newSubtype.name });
      this.newSubtype = { id: '', name: '' };
    },
    addGrantedAbility() {
      if (!this.newGrantedAbility) return;
      if (!this.currentCard.grantedAbilities.includes(this.newGrantedAbility)) {
        this.currentCard.grantedAbilities.push(this.newGrantedAbility);
      }
      this.newGrantedAbility = '';
    },
    selectSkillNode(node) {
      this.selectedSkillNode = node;
    },
    selectSkillTreeNode(uid) {
      this.selectedSkillTreeNodeUid = uid;
    },
    addSelectedSkillNodeAsChild() {
      if (!this.selectedSkillNode) {
        alert('请先在左侧技能库选择一个节点。');
        return;
      }
      const node = createTreeNodeFromLibraryNode(this.selectedSkillNode);
      addChildNode(this.currentSkillTreeDraft.roots, this.selectedSkillTreeNodeUid, node);
      this.selectedSkillTreeNodeUid = node.uid;
    },
    addSelectedSkillNodeAsRoot() {
      if (!this.selectedSkillNode) {
        alert('请先在左侧技能库选择一个节点。');
        return;
      }
      const node = createTreeNodeFromLibraryNode(this.selectedSkillNode);
      addChildNode(this.currentSkillTreeDraft.roots, null, node);
      this.selectedSkillTreeNodeUid = node.uid;
    },
    removeSelectedSkillTreeNode() {
      if (!this.selectedSkillTreeNodeUid) return;
      if (!confirm('删除当前技能节点及其所有子节点？')) return;
      removeTreeNode(this.currentSkillTreeDraft.roots, this.selectedSkillTreeNodeUid);
      this.selectedSkillTreeNodeUid = '';
    },
    moveSelectedSkillTreeNode(direction) {
      if (!this.selectedSkillTreeNodeUid) return;
      moveTreeNode(this.currentSkillTreeDraft.roots, this.selectedSkillTreeNodeUid, direction);
    },
    duplicateSelectedSkillTreeNode() {
      if (!this.selectedSkillTreeNodeUid) return;
      const cloned = duplicateTreeNode(this.currentSkillTreeDraft.roots, this.selectedSkillTreeNodeUid);
      if (cloned) this.selectedSkillTreeNodeUid = cloned.uid;
    },
    toggleSelectedSkillTreeNodeDisabled() {
      if (!this.selectedSkillTreeNode) return;
      this.selectedSkillTreeNode.disabled = !this.selectedSkillTreeNode.disabled;
    },
    toggleSkillTreeNodeCollapsed(row) {
      if (!row?.node) return;
      row.node.collapsed = !row.node.collapsed;
    },
    clearSkillTreeDraft() {
      if (!confirm('清空当前技能结构树草稿？')) return;
      this.currentCard.skillTreeDraft = normalizeSkillTreeDraft({ roots: [] });
      this.selectedSkillTreeNodeUid = '';
    },
    syncSkillTreeSource() {
      this.currentCard.skillLogicSource = this.skillTreeDraftJson;
      alert('已把当前结构树草稿同步到源码。');
    },
    applySkillTreeSource() {
      try {
        const parsed = JSON.parse(this.currentCard.skillLogicSource || '{}');
        if (!Array.isArray(parsed.roots)) throw new Error('源码中缺少 roots 数组');
        this.currentCard.skillTreeDraft = normalizeSkillTreeDraft(parsed);
        this.selectedSkillTreeNodeUid = this.currentCard.skillTreeDraft.roots[0]?.uid || '';
        alert('已从源码恢复结构树草稿。');
      } catch (error) {
        alert(`结构树源码恢复失败：${error.message}`);
      }
    },
    loadRealLogicEntitiesToTree() {
      this.currentCard.skillTreeDraft = buildTreeFromRealLogicEntities(this.currentCard.logicEntities || []);
      this.selectedSkillTreeNodeUid = this.currentCard.skillTreeDraft.roots[0]?.uid || '';
      this.activeLogicMode = 'tree_editor';
    },
    copyRealLogicEntitiesToSource() {
      this.currentCard.skillLogicSource = JSON.stringify({
        format: 'phantom.real_logic_entities.v1',
        warning: '这是从当前卡牌 EffectEntitiesDescriptor.entities 读取出的真实技能实体源码。直接修改后可显式写回 logicEntities。',
        entities: this.currentCard.logicEntities || []
      }, null, 2);
      this.activeLogicMode = 'source';
    },
    applyRealLogicEntitiesSource() {
      try {
        const parsed = JSON.parse(this.currentCard.skillLogicSource || '{}');
        const entities = Array.isArray(parsed) ? parsed : parsed.entities;
        if (!Array.isArray(entities)) throw new Error('源码不是数组，也没有 entities 数组字段');
        this.currentCard.logicEntities = entities;
        alert('已把源码写回当前卡牌的 logicEntities。');
      } catch (error) {
        alert(`真实技能源码写回失败：${error.message}`);
      }
    },
    treeNodeSummary,
    async copyPreview() {
      await navigator.clipboard.writeText(this.previewJson);
    },
    async copyProjectPreview() {
      await navigator.clipboard.writeText(this.projectPreviewJson);
    },
    openPreviewTab() {
      this.activeTab = 'preview_json';
    }
  }
}).mount('#phantom-app');
