
## 🔄 最近更新与性能调优说明

为了使项目在线上（特别是 Render 512MB 内存限制的免费套餐下）更加稳定、高效，且保持一致的美观交互，我们进行了以下深度优化：

### 20. 🧹 Web v3.6 · 未使用逻辑清理与配置规范化（2026-07-27）

- **索引唯一化**：删除运行时不再读取的 `data/index.json`，全站只维护 `data/index_new.json`。
- **阵营字段规范化**：移除中文卡名关键词推断，卡组工坊、关卡编辑器和幻影工坊严格依据 `FACTION` 字段解析阵营；缺失或非法值使用安全默认值 `0`。
- **Phantom 清理**：删除未调用的配置重载函数，以及旧 `zh-CN` 本地化和 `skill_library` 配置重建分支；保留 API 失败时的静态配置降级与旧浏览器草稿迁移。
- **下载配置收口**：运行时和校验脚本只接受 `sections[]`，移除旧根键 `tools[]` 的自动兼容。
- **静态资源去重**：删除根目录 Google 验证副本和被 WhiteNoise 同名静态文件覆盖的 Flask 路由；`robots.txt`、`sitemap.xml` 与 Google 验证文件统一由 `static/` 提供。
- **接口兼容策略**：保留版本与赞助接口的全部历史别名，并保留 Unity 历史错误导出的 PPtr 修复逻辑。
- **安全规则精简**：移除不存在的 message/comment 路径和已被 `/feedback` 覆盖的重复规则。

### 1. 🛡️ 统一并发锁控制 (`extensions.py` / `blueprints/`)

- 将原本局部定义的 `UNITY_TASK_LOCK` 移至统一的 `extensions.py` 中。

- 在卡组打包接口（`/api/quick_export`）以及关卡打包/提取接口（`/api/editor/ab/*`）中全数引入该串行处理锁，彻底杜绝了多模块并发调用 `UnityPy` 加载大包导致服务器发生 OOM 内存溢出崩溃。

### 2. 🗂️ 零碰撞动态临时工作区

- 废弃了原先写死且易发生请求碰撞的 `out/data_assets_36` 静态路径，改用 Python `tempfile.mkdtemp()` 动态分配隔离工作区。

- 利用 Flask 的 `after_this_request` 回调钩子，在打包好的 AB 压缩包成功 stream 下载给用户后，于后台安全、彻底地清理这些动态分配的临时缓存文件夹，实现了零磁盘残留和高并发安全。

### 3. 🎨 界面母版化与统一化重构 (`deck_editor.html` / `phantom.html`)

- **母版继承**：将原本作为独立单页开发的“卡组工坊 Pro”和“幻影卡牌工坊”全部重构并继承自 `base.html`，完美接入全站的主导航头和统一页脚。

- **移动端响应式升级**：对“幻影工坊”在小屏幕下的排版进行了重构，隐藏了会与母版全站底栏发生 Z-Index 冲突的内置底栏，并将原先隐藏的左侧边栏 `.sidebar` 改造为**顶部可横向滑动的水平滚动导航条**，完美解决了移动端下的点击失效与重叠 Bug。
- **数据字段纠偏**：完全还原了幻影工坊底层的 Vue 属性绑定，避免了因引用未定义变量导致的 `TypeError` 卡死，并纠正了后端接口参数命名偏差（如 `message` 与 `msg`）。

### 4. ⚡ 数据加载缓存化 (`logic_unity.py`)

- 对卡牌数据库解包得到的静态底包元数据应用了内存缓存技术（`_cached_extracted_data`），在单次进程生命周期内仅在首次加载时解析一次，此后刷新页面均能秒级响应。

### 5. 📦 大文件上传限制放宽 (`config.py`)

- 将 `Config.MAX_CONTENT_LENGTH` 上限由 `20MB` 放宽至 `150MB`，从而完美兼容 100MB+ 体积的官方及第三方大型 Mod 关卡包的上传和处理。

### 6. 🌐 根除 favicon.ico 404 警告 (`base.html`)

- 统一在 `base.html` 头部嵌入了基于高性能 SVG Data URL 格式的 **📦 网站 Favicon 图标**，不仅美化了浏览器标签页，还完美杜绝了控制台中的 404 资源缺失警告。

### 7. 🧹 物理清理无用历史资产

- 彻底清除了 `data/` 下无引用的 `card_data_1` 原始底包文件和 `card_data_1.json` 废弃配置，为项目仓库减负约 10MB 空间。

### 8. 💬 意见反馈模块重构（契约 / 分层 / Supabase 权限）

- **分层**：路由迁至薄蓝图 + `services/feedback.py`，校验与写库与 HTTP 层解耦。

- **契约统一**：成功 / 失败 / 限流 / 影子封禁均使用 `ok` + `error`/`message` 字段，前端不再出现“限流却显示通用失败”的错位。
- **限流 key**：反馈接口使用 `visitor_ip_key()`，与安全模块真实 IP 一致。
- **类型白名单**：仅接受 `bug` / `feature` / `other`；非法 JSON 用 `silent` 解析，返回 400 而非 500。
- **前端降级**：反馈页改为原生 form + fetch，去掉对 Vue CDN 的强依赖，CDN 失败时页面仍可用。
- **数据库**：提供 `sql/feedbacks.sql` 一键重建表结构、CHECK 约束、索引、RLS 与 GRANT（anon 仅 INSERT）。

### 9. 📥 下载中心重构（分区 + 作品包）

- **分区**：`Mod 内容` / `工具与资源`，列表 Tab 切换，短链 `/downloads/mods`、`/downloads/tools`。

- **形态**：`single` 单文件与 `bundle` 作品包（一层子文件列表，支持推荐项与分卷下载）。
- **体验**：列表封面、合集角标、系列互链、文件级 notes、本地下载计数。
- **运维**：`scripts/validate_downloads.py` 校验目录结构；细节见 `docs/` 下下载中心文档。

### 10. 📱 移动端竖屏深度体验优化

- **响应式重构**：针对移动端竖屏（宽度 <= 640px 且竖屏状态）进行了深度视觉与布局重构。在保持横屏和 PC 端大卡片高级感的同时，彻底解决了小屏下卡片堆叠过长、内容遮挡等问题。
- **核心组件小卡片化**：将首页原有的 `AB 工作台` 与 `幻影引擎` 两个核心大卡片，在小屏下自适应重排为**并排双列的精致小磁贴**，字号、内边距和圆角合理缩小，同时为 `AB 工作台` 注入微缩的应用图标，有效节约了首屏约 80% 的纵向高度。
- **公告卡片精简化**：保留公告卡片的原生设计，但物理缩减了边距 `p-4`，字号按层级缩放，并隐藏了移动端非必要的背景大浮动图标，使得公告占用面积减少约 40%，首屏信息密度显著提升。
- **扁平化横向列表**：为首页辅助工具网格（如卡组编辑器、关卡编辑器等 6 大工具）引入了横向扁平化弹性布局（`Flex Row`），图标靠左文字靠右，避免了多列排版文字严重折行导致的杂乱感，大幅提升了移动端的点按便捷性与浏览质感。
- **赞助卡片图文并排**：优化了“让我吃点垃圾”赞助区域的排版，在竖屏下自动切换为图文并排布局（左侧文案与按钮，右侧微缩赞赏码），避免了单栏长图文排版导致的过度下滑。

### 11. 📇 卡牌索引升级与阵营识别重构（`index_new.json` / `utils/card_index.py`）

全站卡牌元数据统一切换到新版索引，并据此修正卡组工坊等模块长期依赖「中文名关键词猜阵营」的错误逻辑。

**数据源迁移**

| 项目 | 旧版 | 新版 |
|------|------|------|
| 文件 | `data/index.json` | **`data/index_new.json`** |
| 字段 | `GUID`, `UUID`, `NAME_CN`, `TEXTURE_NAME` | 在旧字段基础上增加 **`TYPE`**（单位/魔法/环境）、**`FACTION`**（植物/僵尸）、**`NAME_EN`** |
| 读取入口 | 各模块分散引用 | 仍统一经 `utils/card_index.py` → `load_json_file("index_new.json")` |

- 卡组工坊（`logic_data` → `to_deck_editor_cards`）、关卡编辑器（`to_level_editor_cards`）、幻影工坊（`to_phantom_card_index` / `card_index_meta`）均从同一新索引派生专用格式。
- 旧文件 `data/index.json` 已于 Web v3.6 清理，运行时与维护流程统一使用 `data/index_new.json`。

**阵营识别（核心修复）**

- **旧逻辑**：`infer_faction(NAME_CN)` 用「僵尸 / 急冻魔 / 霹雳舞王…」等硬编码关键词判断 → 对「网球高手」「蹦极管道工」等无关键词僵尸牌会误判为植物（实测约 **211** 张不一致）。
- **新逻辑**：只读取索引字段 `FACTION`（`植物` → `0`，`僵尸` → `1`）；`parse_faction()` 同时兼容数字与英文枚举（`Plant`/`Zombie`/`Plants`/`Zombies`），不再根据卡名关键词推断。
- **卡组工坊前端**（`templates/deck_editor.html`）：新增 `normalizeFaction()`，加卡 / 读 bundle / 本地缓存 / 导出全链路统一为整数 `0|1`，兼容旧 localStorage 中的 `"Plant"` / `"Zombie"` 字符串。
- **打包回填**（`logic_unity.py`）：新卡写入 `Faction` 时改用共享 `parse_faction()`，不再只认 `"Zombie"` 这一种字符串。
- **幻影工坊**：索引同步时一并写入阵营（`Plants` / `Zombies`）；匹配提示展示 `FACTION` / `TYPE`；`to_phantom_card_index` 额外输出 `FACTION_ENUM` 供 UI 枚举绑定。

**各模块输出约定**

| 模块 | 转换函数 | 阵营相关字段 |
|------|----------|--------------|
| 卡组工坊 | `to_deck_editor_cards()` | `Faction: 0 \| 1` |
| 关卡编辑器 | `to_level_editor_cards()` | `faction: 0 \| 1`（新增） |
| 幻影工坊 | `to_phantom_card_index()` | `FACTION`（中文）+ `FACTION_ENUM`（`Plants`/`Zombies`）+ `TYPE` / `NAME_EN` |

**维护提示**：更新卡牌表时只维护 `data/index_new.json`；改索引文件名或字段约定时同步修改 `utils/card_index.py` 中的 `INDEX_FILENAME` 与 `parse_faction()`。Unity 补丁工具里的 `_index.json` 是 AssetStudio 导出索引，与本卡牌元数据无关，勿混淆。

### 12. 🌐 全站谷歌 Chrome 搜索收录与 SEO 优化（GSC）

为了确保 Render 部署的工具箱能够在 Google 浏览器中被完美搜索和收录，同时兼顾夜间休眠的运行策略，我们对全站进行了针对性的 SEO 调优：

- **静态提供 `robots.txt` 与 `sitemap.xml`**：
  - 两个文件统一由 WhiteNoise 从 `static/` 提供，避免同路径 Flask 路由被静态中间件覆盖。
  - `scripts/generate_sitemap.py` 根据 `downloads.json` 生成站点地图并纳入下载详情页；目录更新后应重新运行脚本。

- **补全全局 SEO 元数据**：
  - 在母版 [templates/base.html](file:///C:/Users/15731/Desktop/pvzh%E5%B7%A5%E5%85%B7%E5%8C%85/web/MyProject/templates/base.html) 中将 Title、Description 与 Keywords 重构为高度精准的 PVZH 在线 Mod 辅助工具相关中文关键词，优化谷歌搜索结果的卡片展示。

- **优化爬虫抓取路径（顺藤摸瓜）**：
  - 将下载中心 [templates/tab_downloads.html](file:///C:/Users/15731/Desktop/pvzh%E5%B7%A5%E5%85%B7%E5%8C%85/web/MyProject/templates/tab_downloads.html) 的 Mod 卡片重构为由标准的 `<a>` 标签包裹，并将内部的“查看详情”按钮改造为 `<div>` 从而彻底规避 `<a>` 标签嵌套的 HTML 语法问题，提高谷歌爬虫对 Mod 详情页的抓取效率。

### 13. 🛡️ 安全审计、自唤醒误报与 `security_logs` 权限（2026-07-13）

针对线上日志中周期性 `[SECURITY]` 刷屏与 `permission denied for table security_logs` 做了闭环修复。

**现象**

- 约每 14 分钟出现：`Event fallback: ip=74.220.49.7 … reason=脚本/命令行请求 UA`，UA 为 `python-requests/…`，路径为 `GET /`。
- 同时伴随：`Failed to log to Supabase: permission denied for table security_logs (42501)`。

**结论**

| 项 | 判定 |
|----|------|
| `74.220.49.7` | Render 进程自唤醒经公网回环的**出站 IP**，不是外部攻击；**禁止**加入黑名单 |
| `42501` | Supabase 表权限/RLS 问题（表未建或 anon 无 INSERT），不是典型的 Render Key 配错 |

**代码改动**

- `app.py`：KeepAlive 默认改为 `…/health`；UA `PVZH-KeepAlive/1.0`；可选 `X-Self-Ping-Token` / `SELF_PING_TOKEN`。
- `security.py`：识别 KeepAlive UA/Token 与 `SECURITY_TRUSTED_IPS` 并跳过；脚本 UA 仅记录类事件节流；Supabase 写失败错误信息可区分「表权限 / 表不存在 / JWT」。
- 新增 [`sql/security_logs.sql`](sql/security_logs.sql)：建表、索引、RLS、`GRANT INSERT` 给 anon（与 feedbacks 同模型）。
- `.env.example` / README：补充 `SELF_PING_URL`、`SELF_PING_TOKEN`、`SECURITY_TRUSTED_IPS` 与部署检查清单。

**运维动作（必做）**：在 Supabase SQL Editor 执行 `sql/security_logs.sql`；Render 上确认 `SELF_PING_URL` 指向 `/health`。

### 14. 🔧 Unity 通用回填 `POST /repack` 500 修复（`m_Script` PPtr 被误折叠）（2026-07-13）

**现象**

- 用户流程：预检 `POST /unity/validate-repack` → **200**，随即 `POST /repack` → **500**（错误页约 17KB）。
- 服务端异常形态：`AttributeError: 'str' object has no attribute 'm_FileID'`（经本地复现确认）。

**根因**

`blueprints/unity.py` 的 `transform_json_tree(mode='collapse')` 曾把 **`m_Script`** 列入「字符串嵌 JSON」字段。  
在 Unity 中 `m_Script` 是 **PPtr**（`{m_FileID, m_PathID}` 字典），被 `json.dumps` 成字符串后，`obj.save_typetree()` 必然失败。  
预检只校验 JSON 可解析与路径匹配，**不调用** `save_typetree`，故出现「预检过、回填挂」。

**修复**

- 仅对 `m_Data` / `m_RawData` 等真正可能嵌 JSON 的键做 expand/collapse。
- 识别 PPtr 形态（`is_pptr_like`），禁止 stringify。
- 新增 `restore_pptr_fields()`：兼容历史错误导出（`m_Script` 已是字符串时自动还原）。
- JSON 解析失败回退 `json5`；`env.file.save(packer="lz4")` 失败时回退默认 packer。

**验证**

- 本地对 `recipe_decks_1` / `recipe_definitions_1` / `data_assets_36`：导出 → 回填 → save 通过。
- Flask 测试客户端：`/unpack` → `/unity/validate-repack` → `/repack` 端到端 200。

**说明**：卡组工坊 `logic_unity.py` 一键打包不经过该 transform 路径，本 bug 主要影响 **AB 工作台** 的通用解包/回填。

### 15. 🔧 Unity 工具 CSV 转义丢失修复 & m_Script 强力保护（2026-07-16）

**问题**

1. **转义字符丢失**：导出 CSV 再读取回写时，由于未在 `csv.writer` 显式声明 `lineterminator`，且存在回写时盲目写入无意义空行（3 行）的逻辑，导致带有多行文本或大量转义引号 `\"` 的嵌套 JSON 字符串在 CSV 和 JSON 互转读写时发生斜杠丢失，破坏格式。
2. **`m_Script` 被强行折叠 500**：`m_Script`（或部分 PPtr 引用）在通用解包/回填转换中，即使处于嵌套结构，一旦进入 collapse 逻辑变成字符串，就会导致 UnityPy 的底层 `save_typetree` 无法序列化字典而引发 500 报错。

**解决与优化**

- **解决转义丢失**：在 `FormatManager.to_csv` 中显式指定 `lineterminator='\n'`，并且回写 CSV 时**移除**以往无意义写入 3 空行的逻辑。修改后无论嵌套层级多深，在 CSV 与 JSON 转换中均能够正确并精确地单行或多行一次性读取，不会发生任何反斜杠丢失问题。
- **保护 `m_Script`（拒绝 500）**：在 `transform_json_tree` 核心转换逻辑中，除了 `is_pptr_like` 判断外，明确将 `m_Script` 作为键白名单进行硬性避让（`if k == "m_Script" or is_pptr_like(v): continue`），确保该引用类型绝不参与任何 collapse/stringify 压缩，大幅提升了对复杂 MonoBehaviour 数据回写时的安全系数。

**验证与测试**

- 经编写本地测试脚本测试证明：
  - 嵌套复杂 JSON 和带转义 `\"` 文本的数据转换前后的 CSV 内容可完美 round-trip 还原，且不再夹杂冗余空行。
  - 含有 `m_Script` 的 Typetree 在 `mode='expand'` 与 `mode='collapse'` 时，`m_Script` 所指向的 PPtr 引用字段在全程均得到完美保留而不被折叠为字符串。
  - 全部单体断言测试均一次性通过。

### 16. 🔧 Unity TextAsset `m_Script` 转义/换行修复（双语义）（2026-07-16）

**问题**

上一版为防 MonoBehaviour 回填 500，对 **`m_Script` 键名硬性 `continue` 跳过**。  
但在 **TextAsset** 中，`m_Script` 不是 PPtr，而是整段文本（例如 `card_data_5` 的卡牌 JSON，约 7.7MB，原文带真实换行）。  
硬跳过后 `json.dumps` 会把正文二次转义成：

```json
"m_Script": "{\r\n    \"1\": {\r\n ..."
```

整文件几乎只有 2 行真实换行，编辑体验极差（`Unpacked_card_data_5` 即此现象）。

**解决**

- **`m_Script` 双语义**：
  - 值是 PPtr 字典 `{m_FileID, m_PathID}` → `is_pptr_like` 跳过（MonoBehaviour）
  - 值是 JSON 文本字符串 → 纳入 `STRING_EMBEDDED_JSON_KEYS`，expand 成对象 / collapse 回字符串（TextAsset）
- **不再按键名一刀切**；判定只看值形态。
- collapse 时 `auto` 紧凑 dumps（语义等价、体积更小）；`raw` 保留 indent=4，并可按原文本换行风格还原 CRLF。

**验证**

- 使用目录 `card_data_5`：expand 后导出 `Unpacked_card_data_5`，真实换行约 13 万行，正文可正常阅读。
- expand → 导出 JSON → 再 collapse → `save_typetree` → 重载 Bundle：与原文 `json.loads` 语义全等。
- 合成 MonoBehaviour：`m_Script` PPtr 全程不被 stringify；`m_Data` 仍可 expand/collapse。

### 17. 🛠️ 线上稳定性 & SEO 闭环（反馈 / 送卡 / 静态 / Gunicorn / 索引）（2026-07-17）

对照 Render access log 与线上实测，按优先级修复一批「日志看起来坏、实际更糟/或被误判」的问题。

#### P0 · 反馈接口「一直失败 / 像 404」

**根因（代码级）**

- `feedbacks` 表对 `anon` **仅 GRANT INSERT、无 SELECT**（设计如此，防列表被扫）。
- `supabase-py` 默认 `insert(..., returning=representation)` → PostgREST 插入后 **SELECT 回读**。
- 无 SELECT 时插入链路失败；PostgREST 对「表未暴露 / schema cache」等也会表现为 **HTTP 404（PGRST205）**，容易被当成「路由 404」。
- 表结构本身往往是对的——问题在 **写库客户端约定**，不在 CHECK 约束。

**修复**

- `services/feedback.py`：`insert(..., returning=ReturnMethod.minimal)`。
- 异常归类为 `TABLE_NOT_FOUND` / `PERMISSION_DENIED` / `CONFIG_ERROR` / `STORAGE_ERROR`，运维可读。
- `security_logs` 写入同样改为 `minimal`（同类坑）。
- `sql/feedbacks.sql` 补充注释说明此约定。

#### P0 · `/api/send-cards` 间歇 500

**根因**

- `token` / `persona_id` 非字符串时 `.strip()` → `AttributeError` → 裸 500。
- 上游 EA 网络类异常未细分类；响应体解析不够稳健。
- 上游鉴权失败本应 200 + `success:false`，却被未捕获异常打成 500。

**修复**

- 全量 `str(... or '').strip()`；`get_json(silent=True)`。
- 安全解析上游 body；`Timeout`/`ConnectionError`/`RequestException` 分别 504/503/502。
- 上游非 200 时仍返回 JSON 契约 + `error` 提示（Token 过期等），避免前端只看到「状态码 500」。

#### P1 · 日志里 js/css/png「200 0」

**结论**

- 线上实测 body **有内容**；Gunicorn access log 在 **无 Content-Length / sendfile** 时常把长度记成 `0`（假象）。
- 接入 **WhiteNoise** 托管 `/static/`，正确写出 `Content-Length` 与缓存头，日志与浏览器行为一致。

#### P2 · Gunicorn 频繁重启

**结论**

- Free 套餐 **空闲休眠** 是主因（日志里 `==> Running 'gunicorn app:app'` 与夜间/凌晨冷启动一致），不全是 OOM。
- 若 Dashboard 使用 `render.yaml` 旧 Start Command：`--max-requests 50` 过激进，会加剧 worker 轮换。
- 调整为：`workers 1 --threads 4 --max-requests 500 --max-requests-jitter 50`。
- KeepAlive 改为 **全天** 每 14 分钟 ping `/health`（原仅北京 08–24），减轻 Googlebot 夜间撞冷启动。

#### SEO · 仅 `/unity` 可被搜到

**原因（综合）**

- Free 冷启动导致爬虫超时/软 404；unity 访问多、常温。
- 缺 `canonical` / `lastmod` / 分页面 description；部分页面同质。

**修复**

- `base.html`：`robots=index,follow`、`link rel=canonical`、`og:url`。
- 主要工具页补独立 `meta_description`。
- 静态 `sitemap.xml` 包含 `lastmod`；`robots.txt` 明确 `Disallow: /api/`、`/security/`。
- 全天保活 + 建议 GSC 重新提交 sitemap。

#### 低 · favicon.ico 404

- 新增 `static/favicon.svg` + 路由 `GET /favicon.ico`，消除浏览器/Googlebot-Image 的 404 噪音。

**本地验证（Flask test_client）**

- `/favicon.ico` 200；`/static/js/phantom/main.js` 200 且 Content-Length=文件大小。
- 反馈空内容 → 400；无 Supabase 配置 → 503 `CONFIG_ERROR`。
- 送卡坏类型 → 400（不再 500）；假 Token 上游 401 → HTTP 200 + `success:false`。

### 18. 🛠️ 性能与安全加固 & 赞助体验升级（2026-07-20）

为了进一步增强 Unity 文件打包的稳定性、防止恶意脚本爬取、避免限流误判，同时优化赞助展示与交互体验，我们进行了以下重要升级：

#### P0 · Unity 回填打包 (`/repack`) 硬核加固
- **异步响应与错误提取**：fetch 客户端统一请求 JSON 响应。若打包过程中抛出异常，不再全页展示 HTML 错误，而是前端提取精准的 JSON 错误并通过内联警告提示给用户，避免破坏当前解包页面状态。
- **保存多级回退重试**：打包字节保存时增加 lz4 压缩模式和默认无参数模式的双重退回机制（`_save_bundle_bytes`），最大限度规避特定 Unity 资源打包敏感崩溃。
- **MonoBehaviour `save_typetree` 智能容错**：在 `obj.save_typetree` 失败时，自动触发 PPtr 修复逻辑 (`restore_pptr_fields`) 并重试，专门解决嵌套对象中 `m_Script` 被历史版本或第三方解包错误导出为字符串引发的 500 报错。
- **OOM 内存防溢出与 GC 强收回**：显式捕获 `MemoryError` 内存不足异常，在写出 Bundle 大文件前后主动调用 `gc.collect()` 销毁临时 `saved_bytes` 释放内存，并向用户提示合理缩小补丁 ZIP 建议。

#### P1 · 限流与 IP 穿透修复 (`visitor_ip_key` / `limiter`)
- **真实客户端 IP 限流**：将限流器 (`extensions.py`) 中的 `key_func` 从 `get_remote_address` 修复为 `visitor_ip_key`。此前，Render 负载均衡后 `remote_addr` 全为 `127.0.0.1`，导致全站用户共用一个限流桶而导致频繁 429 报错；修复后已实现精确定位单个客户端 IP。
- **健康检查豁免限流**：确保 `/health` 路由豁免于 API 默认限流限制，避免 KeepAlive 触发限流桶。
- **串行任务忙时短排队**：修改 `acquire_unity_lock`，当并发请求时，不再立刻返回 429，而是支持在合理时间（25秒）内进行非阻塞轮询短排队，解决用户预检与回填交替请求时的短暂竞态问题。

#### P1 · 安全告警降噪与恶意 User-Agent 阻断
- **命令行/脚本客户端硬阻断**：在 `security.py` 中对明确带有 `python-requests` 等命令行探测特性的 UA 请求，直接在全局安全拦截处返回 403 Forbidden，不进行渲染，从而节省 Render 服务器 CPU 和带宽资源。
- **KeepAlive 日志大降噪**：对成功的 `/health` 保活请求，从原先每次均打印日志改为每 12 次成功（约 3 小时）仅输出一条汇总日志，避免 Render 日志区被健康检查大面积刷屏。

#### P2 · 全站赞助与支持体验升级
- **母版交互入口改版**：全站 Header 与 Footer 移除了无关联的 Bilibili 作者链接，改版为统一的“赞助与支持”交互按钮（桌面端/移动端自适应适配）。
- **赞赏弹窗重设计**：重新设计了 `support-modal` 弹窗。不再要求用户点击外部链接去 B 站，而是直接在弹窗内集成了微信/支付宝赞助二维码，配以优雅的渐变背景与心形图标。
- **手动触发与免弹起机制**：暴露全局 `window.openSupportModal()` 接口供导航按钮点击调用。当用户手动触发时，自动重置“不再弹出”的勾选框；若用户勾选了“不再弹出”且由系统自动弹出时，则不再强行弹窗。
- **移动端页面顺序与标题文案优化**：在 `index.html` 首页，移动端下赞助卡片调整为 order-1 优先排在顶部，并修改为更和谐大气的“赞助与支持”文案，引导爱开发电支持。

### 19. 🚀 下载中心多源并发竞速加速与资源升级（2026-07-22）

为了解决国内访问 GitHub Release 大文件附件时，部分公共镜像源偶发返回 404 / 403 导致浏览器无法自动切源下载的问题，我们对下载中心进行了全链路的多源并发竞速重构：

#### ⚡ 多源并发竞速与 404 故障源自动剔除
- **真实数据包并发校验**：前端镜像竞速引擎在点击下载或打开测速弹窗时，并发向 7 个公共 GitHub 镜像节点发起 `GET Range (bytes=0-100)` 请求。
- **404/50x 智能过滤**：自动识别 `HTTP 404`、`403`、`5xx` 以及 HTML 格式的错误响应页，并在 UI 中标红打叉 (`❌ 404 已过滤`) 自动予以剔除，彻底解决误连 404 节点引发浏览器下载卡死的问题。
- **首个有效源即刻锁定**：首个响应 `HTTP 200/206 OK` 的有效节点会秒级锁定为最佳可用源（如 `🚀 Ghproxy Net (42ms)`），同时自动取消 (Abort) 其它冗余并发请求以节约带宽。
- **倒计时自动与手动自由下载**：显示 2 秒自动跳转下载倒计时，同时提供“记住偏好”与手动点击任意 200 OK 镜像节点的下载入口。

#### 🌐 后端镜像节点优先级与 API 扩展
- **推荐节点优先级调优**：将后端 [blueprints/downloads.py](file:///C:/Users/15731/Desktop/pvzh工具包/web/MyProject/blueprints/downloads.py) 默认重定向镜像源调优为高可用的 `ghproxy.net` 与 `gh-proxy.com`，解决原推荐节点偶发 404 的问题。
- **多镜像 REST API**：新增 `/api/download/mirrors` 接口，方便前端以及第三方获取指定资源或 GitHub 链接的完整镜像节点 metadata。

#### 📦 Release 附件资源更新 (`data/downloads.json`)
- **PVZH 卡牌 DIY v4.5.0**：更新为最新版本 `v4.5.0` APK 下载链接，并同步更新了版本号与换源链接。
- **PVZH 刷钻工具 1**：新增刷钻与刷卡替换辅助工具 1 (`43.8 MB`) APK 资源。
- **PVZH 刷钻工具 2**：新增刷钻轻量/备用工具 2 (`12.7 MB`) APK 资源。




