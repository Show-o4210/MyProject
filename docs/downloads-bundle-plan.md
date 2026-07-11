# 下载中心 · 作品包（Bundle）方案与实施计划

> 状态：已采纳，分步实施中  
> 关联：`docs/downloads-refactor-log.md`（分区框架）  
> 原则：**作品容器 + 一层子文件；不做通用网盘；不做服务端动态打包。**

---

## 1. 目标

让下载中心支持两类条目：

| 形态 | 含义 | 典型场景 |
|------|------|----------|
| **single** | 一个条目对应一个下载地址 | DIY.apk、一键替换 |
| **bundle** | 一个作品/合集下挂多个可独立下载文件 | 英雄合集分卷、系列资源、完整包+单件 |

用户可以：

1. 在列表看到「合集 · N 个文件」
2. 进入详情像打开文件夹一样浏览子文件
3. 单独下载某个子文件
4. 通过预置的「完整包 / 推荐项」一键拿齐内容

---

## 2. 产品决策（冻结）

| # | 决策 |
|---|------|
| 1 | 分区（Mod / 工具与资源）不变；bundle 是 **item 内部能力** |
| 2 | 只允许 **一层** `files[]`，禁止无限嵌套目录 |
| 3 | 系列关系用 `series_id` 等轻量字段（二期互链），不嵌套 folder |
| 4 | 「全部下载」= 预置完整包文件（`recommended` 或文案标明），**不**服务端 zip |
| 5 | 子文件 **不单独做详情页**，只在 bundle 详情内下载 |
| 6 | 旧 single 条目全兼容（无 `kind` 且有 `url` 视为 single） |
| 7 | 不做：动态打包、多选批量触发下载、无限树 UI、投稿后台 |

---

## 3. 数据模型

### 3.1 条目公共字段

沿用现有：`id`, `name`, `description`, `details`, `usage`, `notes`,  
`version`, `tag`, `icon`, `size`, `updated_at`, `images`

新增：

| 字段 | 类型 | 说明 |
|------|------|------|
| `kind` | `"single"` \| `"bundle"` | 可省略：有 `files` 则 bundle，否则 single |
| `url` | string | single 必填；bundle 可选（若有则作为快捷「整项下载」） |
| `files` | array | bundle 的子文件列表（仅一层） |
| `series_id` | string | 可选，二期 |
| `series_name` | string | 可选，二期 |
| `series_order` | number | 可选，二期 |

### 3.2 子文件 `files[]` 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `id` | 是 | 在 **同一 item 内** 唯一 |
| `name` | 是 | 显示名 |
| `url` | 是 | 直链 |
| `description` | 否 | 一行说明 |
| `size` | 否 | 展示用 |
| `tag` | 否 | 如 ZIP / APK |
| `updated_at` | 否 | |
| `recommended` | 否 | `true` 时置顶并作为默认整包入口 |
| `notes` | 否 | 短提示（可选，UI 可后做） |

### 3.3 解析约定（后端规范化）

```text
if item.files 非空 → kind = bundle
else → kind = single

bundle 默认下载目标（item 级 /api/download/<item_id>）：
  1. item.url（若存在）
  2. 第一个 recommended=true 且有 url 的 file
  3. 若仅有 1 个 file → 该 file.url
  4. 否则 → 不自动跳转（详情页引导选文件）
```

### 3.4 示例（结构示意）

```json
{
  "id": "demo-hero-pack",
  "kind": "bundle",
  "name": "示例：英雄资源合集",
  "description": "演示作品包形态：可下完整包或分卷。",
  "version": "0.1",
  "tag": "合集",
  "icon": "folder_zip",
  "updated_at": "2026-07-12",
  "images": [],
  "files": [
    {
      "id": "full",
      "name": "完整包",
      "description": "含全部子资源，推荐优先下载。",
      "size": "—",
      "tag": "ZIP",
      "recommended": true,
      "url": "https://example.invalid/full.zip"
    },
    {
      "id": "part-a",
      "name": "分卷 A",
      "size": "—",
      "tag": "ZIP",
      "url": "https://example.invalid/a.zip"
    }
  ]
}
```

> 上线真实资源时替换 `url`；示例可用占位链或指向已有 Supabase 文件。

---

## 4. 路由

| 方法 | 路径 | 行为 |
|------|------|------|
| GET | `/downloads` | 列表（已有） |
| GET | `/downloads/<item_id>` | 详情；模板按 kind 分支 |
| GET | `/api/download/<item_id>` | single / bundle 默认目标 302；限流 |
| GET | `/api/download/<item_id>/<file_id>` | **新增** 子文件 302；限流 |

限流：与现网一致（如 `5 per minute`），两接口均可挂 limiter。

---

## 5. UI 规格

### 5.1 列表卡片

- single：与现网一致  
- bundle：
  - 角标/标签含「合集」或沿用 `tag`
  - 展示 `N 个文件`
  - 仍只进详情，不在列表展开树

### 5.2 详情页

**single：** 保持现有「立即下载」+ 介绍/步骤/注意  

**bundle：**

- 顶栏：分区徽章 + 合集标识  
- 主区：介绍 / 预览 / 步骤 / 注意（同现网）  
- **文件列表区（核心）：**
  - 表格或卡片列表：名称、说明、大小、类型、下载按钮  
  - `recommended` 置顶并视觉强调（如「推荐」徽章）  
- 侧栏：
  - 文件信息（版本、分区、文件数等）  
  - 若存在默认下载目标：显示「下载推荐项 / 完整包」按钮  
  - 否则文案：请从文件列表选择  

### 5.3 不做（本计划范围外）

- 文件独立 URL 详情页  
- 多选 checkbox + 一键触发多个浏览器下载  
- 文件夹面包屑多级导航  

---

## 6. 分阶段实施

### Phase 0 · 计划定稿

- [x] 本文档  
- [x] 进度日志同步  

### Phase 1 · 数据与 API（后端框架）

- [x] `normalize_item`：推导 kind、规范化 files  
- [x] `find_file(item_id, file_id)`  
- [x] `resolve_download_url(item)` 默认目标  
- [x] 路由 `/api/download/<item_id>/<file_id>`  
- [x] 旧 single 与无 files 条目行为不变  
- [x] tools 三条补 `kind: "single"`  

### Phase 2 · UI + 示例数据

- [x] 列表：合集角标 + 文件数  
- [x] 详情：bundle 文件列表 UI  
- [x] mods 区放入 **1 条示例 bundle**（`demo-hero-pack`）  
- [x] 模块级自检（catalog / find_file / 路由注册）  

### Phase 3 · 体验增强

- [x] `series_*` 同系列互链（详情页「同系列其它作品」）  
- [x] 文件级 `notes` 展示  
- [x] 下载计数（已于 2026-07 移除）  
- [x] 列表封面图（`cover` 或 `images[0]`）  
- [x] 校验脚本 `scripts/validate_downloads.py`  
- [x] 存储命名约定：`workshop-downloads/{mods|tools}/{item_id}/{file_id}.ext`  

### Phase 4 · 运营向（更后）

- [ ] 投稿 / 管理后台  
- [ ] 与 news 联动  
- [ ] 计数迁移到 Supabase（已废弃计划）  

---

## 7. 验收清单（Phase 1–2）

1. `/downloads?section=tools` — 原 3 条仍可打开、可下载  
2. `/downloads?section=mods` — 可见示例 bundle 卡片，显示文件数  
3. 进入 bundle 详情 — 见文件列表，推荐项置顶  
4. 点子文件下载 — `/api/download/<item>/<file>` 302  
5. 点「下载推荐项」（若有）— item 级 API 落到 recommended/url  
6. single 详情 — 无文件列表区，行为与改前一致  
7. 错误 id — 404 友好页  

浏览器走查请本地启动后按上表点一遍。

---

## 8. 变更文件

| 文件 | Phase | 说明 |
|------|--------|------|
| `docs/downloads-bundle-plan.md` | 0 | 本计划 |
| `docs/downloads-refactor-log.md` | 0–2 | 进度同步 |
| `blueprints/downloads.py` | 1 | normalize / find_file / 双下载路由 |
| `data/downloads.json` | 1–2 | kind + 示例 bundle |
| `templates/tab_downloads.html` | 2 | 合集角标 |
| `templates/download_detail.html` | 2 | 文件列表 UI |

---

## 9. 风险与规避（摘要）

| 风险 | 规避 |
|------|------|
| 做成网盘 | 一层 files + 无多级 UI |
| 默认不知下哪个 | recommended + 侧栏说明 |
| id 冲突 | file.id 在 item 内唯一；查找带 item 作用域 |
| 免费托管扛不住打包 | 禁止服务端聚合成 zip |
| 示例链与标题不符 | 条目标明【示例】；url 复用已有 heroes.zip 仅验跳转 |

---

## 10. 进度快记

| 日期 | 事项 | 状态 |
|------|------|------|
| 2026-07-12 | 分区框架落地 | 完成 |
| 2026-07-12 | Bundle 方案评审并采纳 | 完成 |
| 2026-07-12 | Phase 0 计划文档 | 完成 |
| 2026-07-12 | Phase 1–2 实现 | 完成 |
| 2026-07-12 | 修复 Jinja `dict.items` 冲突（分区列表改用 `entries`） | 完成 |
| 2026-07-12 | Phase 3 体验增强 + curl 验收 | **完成** |
| （待定） | Phase 4 | 未开始 |

### 示例条目

- id：`demo-hero-pack`（bundle）+ `demo-card-skin`（single），同系列 `demo-series-2026`  
- 正式上架时替换文案与真实 URL，或删除示例后写入真实作品  

### 已知坑

| 问题 | 处理 |
|------|------|
| Jinja 中 `section.items` 变成 `dict.items` 方法 | 运行时分区字段改名为 `entries`；JSON 仍写 `items` |

### 上架命名约定

```text
Supabase Storage 建议路径：
  workshop-downloads/mods/{item_id}/{file_id}.zip
  workshop-downloads/tools/{item_id}/{file_id}.apk
```

校验：`python scripts/validate_downloads.py`
