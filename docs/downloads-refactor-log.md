# 下载中心重构 · 工作过程记录

> 用途：对照进度、比对决策与实现范围。  
> 原则：**先搭框架，复杂功能后置。**

---

## 1. 背景与目标

### 1.1 原状问题

| 点 | 说明 |
|----|------|
| 结构过轻 | 单层 `tools[]` 列表，只有「资源下载」一种心智 |
| 内容错位 | 现有条目（DIY、一键替换、刷英雄）本质是工具/素材，不是成品 Mod |
| 扩展困难 | 后续若上架作品，会与工具混在同一列表，难找、难运营 |
| 文档偏差 | README 曾写「下载计数」，代码仅 `redirect`，未实现 |

### 1.2 产品决策（已确认）

- 下载中心按用途分为两大分区：
  1. **Mod 内容** — 面向游玩/体验的成品（卡包、英雄改动、关卡包等）
  2. **工具与资源** — 面向制作/运维（辅助软件、替换工具、底包、素材）
- 现有 3 条全部归入 **工具与资源**
- 条目支持两种形态：**single**（单文件）与 **bundle**（作品包 / 一层子文件）
- 作品包方案见：`docs/downloads-bundle-plan.md`
- 不做计数、筛选、投稿、无限文件夹、服务端动态打包等（见 bundle 计划 Phase 3+）

### 1.3 归类原则（边界）

| 判断 | 归入 |
|------|------|
| 有明确作品向说明，安装后游戏内可见效果 | Mod 内容 |
| 主要用于制作、替换、修补、当底包 | 工具与资源 |
| 含糊时 | 优先 **工具与资源**，避免污染 Mod 区 |

---

## 2. 范围对照

### 2.1 已完成

**分区框架**

- [x] `downloads.json` → `sections[]`
- [x] 现有 3 条迁入 `tools`，并标 `kind: single`
- [x] 列表 Tab + 空态 + 详情分区徽章
- [x] 短链 `/downloads/mods`、`/downloads/tools`
- [x] 兼容旧根键 `tools: []`

**作品包 Bundle（Phase 1–2）**

- [x] `kind` / `files[]` / `recommended` / 默认下载解析
- [x] `GET /api/download/<item_id>/<file_id>`
- [x] 列表合集角标 + 文件数
- [x] 详情文件列表 UI（推荐置顶）
- [x] Mod 区示例：`demo-hero-pack`
- [x] 计划文档：`docs/downloads-bundle-plan.md`

**体验增强（Phase 3）**

- [x] 修复 Jinja：`section.items` → 运行时 `entries`
- [x] `series_*` 同系列互链
- [x] 文件级 notes
- [x] 列表封面（cover / images[0]）
- [x] 本地下载计数 `data/download_counts.json`（已于 2026-07 移除）
- [x] `scripts/validate_downloads.py`
- [x] 存储命名约定写入计划文档

### 2.2 明确不做（后续迭代）

- [ ] 列表页快捷下载双按钮
- [ ] 分区内筛选 / 搜索 / 排序
- [ ] 扩展字段：`author`、`tutorial_url`、`platforms`、`checksum`、`changelog` 等
- [ ] 无限嵌套文件夹、服务端动态打包
- [ ] 投稿 / 后台管理 / 与 `news.json` 联动
- [ ] 计数迁 Supabase（已废弃计划）

---

## 3. 数据模型（当前）

文件：`data/downloads.json`

```text
sections[] → items[] →
  single: url + 元数据
  bundle: files[{ id, name, url, recommended, ... }]  // 仅一层
```

规范化后：

- 分区列表键名为 **`entries`**（避免 Jinja `dict.items`）  
- 条目额外：`kind`, `file_count`, `default_download_url`, `cover`, `series_*`  
- 子文件额外：`notes`

完整字段见 `docs/downloads-bundle-plan.md`。

### 3.1 兼容

- 无 `kind`：有 `files` → bundle，否则 single  
- 旧根键 `tools: []` 仍可映射为双分区  
- JSON 仍写 `items`，仅 Python/模板用 `entries`

---

## 4. 路由与页面

| 路由 | 行为 |
|------|------|
| `GET /downloads` | 列表；`?section=` 切换 Tab，默认 `mods` |
| `GET /downloads/<item_id>` | 分区 id → Tab；否则详情（含系列互链） |
| `GET /api/download/<item_id>` | 默认目标 302 |
| `GET /api/download/<item_id>/<file_id>` | 子文件 302 |

| 其它 | 说明 |
|------|------|
| `scripts/validate_downloads.py` | 结构校验 |

---

## 5. 变更文件清单

| 文件 | 说明 |
|------|------|
| `data/downloads.json` | 分区 + bundle + 系列示例 |
| `blueprints/downloads.py` | 全量下载中心逻辑 |
| `templates/tab_downloads.html` | Tab + 封面 + entries |
| `templates/download_detail.html` | 文件列表 / 系列 / 计数 |
| `scripts/validate_downloads.py` | 校验 |
| `docs/*` | 计划与进度 |

---

## 6. 时间线

| 日期 | 事项 | 状态 |
|------|------|------|
| 2026-07-12 | 确认 Mod / 工具二分 | 完成 |
| 2026-07-12 | 分区框架 + Bundle Phase 0–2 | 完成 |
| 2026-07-12 | 修复 items 冲突 + Phase 3 + curl 验收 | 完成 |
| （待定） | Phase 4：投稿 / 公告 / 计数上云 | 未开始 |

---

## 7. 本地自检清单（curl 已跑通）

1. `GET /downloads` → 200，无 TypeError，有合集封面与 demo 卡片  
2. `GET /downloads?section=tools` → 200，含 pvzh-DIY  
3. `GET /downloads/demo-hero-pack` → 200，文件列表 + 同系列链到 demo-card-skin  
4. `GET /api/download/demo-hero-pack` / `.../part-a` / `pvzh-DIY` → 302  
5. `GET /downloads/mods` → 302 到 `?section=mods`  
6. `GET /downloads/not-exist` → 404  
7. `python scripts/validate_downloads.py` → 通过  

---

## 8. 后续建议优先级

1. 真实作品替换示例条目  
2. 列表快捷下载按钮、筛选搜索  
3. Phase 4 运营能力  

---

## 9. 备注

- **Jinja 坑**：分区条目请用 `section.entries`，不要用 `.items`。  
- 下载计数为本地 JSON，Render 多实例/无盘会丢；上云再迁 Supabase。  
- 对照进度：本文件 + `downloads-bundle-plan.md`。
