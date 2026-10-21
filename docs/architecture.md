# 架构说明

## 应用组成

`app.py` 创建 Flask 应用、加载配置和安全处理器、初始化限流器、注册蓝图，并启动 Render 自唤醒定时任务。静态文件由 WhiteNoise 提供。

主要分层如下：

- `blueprints/`：HTTP 路由、请求解析和页面渲染。
- `archive/editors/`：已归档的关卡/卡组实现、专用数据、底包与历史测试，不参与在线运行。
- `utils/`：Unity 任务隔离、资源预算、JSON 清洗和配置读取。
- `data/`：公告、版本、赞助、单一下载链接和玩家精选目录。
- `templates/` 与 `static/`：Jinja2 页面和前端资源。
- `sql/`：Supabase 表结构、RLS 与权限脚本。

## 蓝图与功能

| 模块 | 主要职责 |
| --- | --- |
| `home.py` | 首页、鸣谢页、robots 与动态 sitemap |
| `unity.py` | AssetBundle 文本解包和回填 |
| `deck_editor.py` | 卡组旧页面和 API 的 HTTP 410 响应 |
| `level_editor.py` | 关卡旧页面和 API 的 HTTP 410 响应 |
| `phantom.py` | 幻影引擎归档说明及旧 API 的 HTTP 410 响应；原实现位于 `archive/phantom/` |
| `downloads.py` | 单一夸克网盘超链接页面 |
| `version.py` | APK 版本查询接口 |
| `sponsors.py` | 赞助相关接口 |

## 关键数据流

关卡与卡组工具于 2026-10-21 正式归档到 `archive/editors/`；幻影引擎位于 `archive/phantom/`。专用 Python 实现、模板、卡牌索引、配置、JSON Worker 和底包不再参与网站运行。生产蓝图只返回归档页面或 JSON HTTP 410，不创建 Unity 任务、不加载数据、不清除浏览器历史数据。首页、导航及动态/静态 sitemap 撤下旧入口，原“可能关闭”维护公告与 QQ 引流已移除。

`app.py` 仍注册轻量退役蓝图，以兼容旧 URL；`utils/unity_worker.py` 仅分派 `unpack` / `repack`。旧任务分派、输入校验、文档和测试快照保存在归档目录。通用 Unity 回归测试继续读取归档中的三个底包作为样本。

Unity 页面使用解包 / 回填双页签，JSON/CSV 直接选择，auto/manual 兼容选项默认折叠；任务处理中锁定表单与页签，错误和下载状态分别显示在所属表单。通用 Unity 工作台接收用户上传的 Bundle，支持 JSON/CSV 文本导出、受限补丁回填。Unity 重任务共用 `extensions.py` 中的并发控制，避免低内存实例同时处理多个包。

回填直接提交原 Bundle 和修改 ZIP，不再提供 `/unity/validate-repack`、fast/full 预检或 `require_validate`。独立结构检查及 `/unity/inspect` 接口已移除。正式写入保留 path_id / `_index.json` 匹配、嵌入 JSON 转换和 PPtr 兼容；CSV 标量根据原 typetree 的类型还原。

补丁预算集中于 `utils/patch_limits.py`：ZIP 最多 2048 条目、文件名 512 字符、目录元数据 4 MiB、单成员 48 MiB、累计声明解压大小 128 MiB、每次请求实际读取 64 MiB、压缩比最多 200:1，按最多 64 KiB 分块读取。ZIP 目录尾记录先于 `ZipFile` 构造检查；全部成员元数据先于任何成员正文检查。仅读取用于匹配的索引和实际匹配对象的补丁，不执行 `testzip()`。在线版只支持普通非加密、非分卷、不含 ZIP64 目录的存储/Deflate ZIP。

格式预算：索引 10 MiB，JSON/CSV 各 40 MiB，JSON5 回退解析 2560 KiB；JSON 最多 64 层、500000 节点（解析前另限制结构标记数量），CSV 最多 20000 行、32 列、单字段 8388608 字符。CSV 解析时同步设置解析器字段上限，结束后恢复原值。大 JSON5 应转换为标准 JSON；超预算返回中文 413，输入格式错误返回中文 400。失败立即清理临时目录并释放 Unity 锁；成功在下载流关闭后清理。

旧版卡片补丁补充基线：用户提供的 `card_data_1` TextAsset 展开后为 241267 节点、24 层容器嵌套；对应约 12 MiB 的补丁有 404007 个结构标记。500000 节点/1000000 结构标记预算为该正常结构保留约两倍余量。解析仍先检查原文本大小、深度及结构标记，仅当标准 JSON 失败时尝试去掉双引号字符串外的尾逗号后重新使用标准解析器；重试失败才对原文本使用受限 JSON5 解析。解析后的节点限制仍执行，不改变导出与小型 API 预算。

导出预算集中在 `utils/export_limits.py`：从已加载文件目录迭代对象，避免 Environment.objects 先构造完整对象列表。最多 10000 对象、256 个 Bundle 内文件、16 层文件嵌套；名称/类型/文件名最长 512 字符。

`/unpack` 只导出 MonoBehaviour / TextAsset 文本对象，支持 JSON/CSV 和 auto/manual 文本处理，始终输出索引与摘要。图片、raw、通用高级对象处理与四种导出预设已移除；提交旧 preset/types/include_images/include_index 参数或非法格式返回中文 400。`/repack` 在加载 Bundle 前拒绝 ZIP 中非 JSON/JSON5/CSV 的补丁文件，匹配到其他对象类型也返回中文 400，不静默忽略不支持的补丁。导出对象失败计数保留，但资源预算异常必须立即终止整次请求。Pillow 不再作为项目直接依赖，UnityPy 自身可能仍引入它。

| 导出预算 | 默认值 |
| --- | ---: |
| 遍历对象 | 10000 |
| 实际输出文件（含索引及摘要） | 5000 |
| 单文本对象 / 累计文本 | 16 / 64 MiB |
| 单源对象二进制 / 累计读取 | 16 / 64 MiB |
| 单对象结构节点 / 累计节点 | 500000 / 2000000 |
| 文本结构深度 / 单字符串长度 | 32 层 / 2097152 字符 |
| 嵌入 JSON 展开前正文 | 8 MiB UTF-8 字节 |
| 所有成员未压缩文本 | 64 MiB |
| 输出 ZIP（含中心目录） | 32 MiB |
| 单请求临时磁盘（保守计入 multipart 暂存） | 384 MiB |

源对象 byte_size 在库读取前检查；文本展开用迭代遍历，复用原 JSON 结构标记检查器且不改变回填默认值，JSON5 回退保留 256 KiB 上限。JSON 分段写入 ZIP，CSV 行写入时计数。ZIP 文件写入器在压缩输出、回写头部、最终中心目录写入前检查实际大小。预算超限中文 413，异常释放锁并删除半成品，成功沿用下载流关闭后的清理。

2026-10-02 真实文本资源基线如下；导出摘要字段精简后 ZIP 大小会略有变化。

| Bundle | 对象总数 | 文本导出对象 / ZIP 文件数 | 未压缩内容字节 | ZIP 字节 | 临时磁盘保守峰值字节 |
| --- | ---: | ---: | ---: | ---: | ---: |
| data_assets_44 | 2408 | 2403 / 2405 | 18281030 | 2112933 | 13350501 |
| recipe_decks_1 | 109 | 107 / 109 | 348408 | 82412 | 128508 |
| recipe_definitions_1 | 144 | 140 / 142 | 210644 | 84523 | 123047 |

JSON 和 CSV 的六次真实导出均无失败对象；CSV 最大未压缩 8137380 字节、ZIP 1807441 字节。单对象展开 JSON 最大 7095592 字节；data_assets_44 的单对象 JSON P50/P95 为 1431/5912 字节，另外两个包的 P50 为 3130/887 字节。最大源对象 1143932 字节；最大单对象结构 297329 节点、深度 10，最大请求累计 792369 节点、读取源数据 5306540 字节。对象预算约最大实例的 4.15 倍、输出文件 2.08 倍、单文本 2.36 倍、累计内容 3.67 倍、ZIP 15.9 倍；16 MiB 源对象预算约 14.7 倍，64 MiB 累计源读取约 12.6 倍；单结构节点 1.68 倍、累计节点 2.52 倍、深度 3.2 倍。普通单字符串预算为 2 Mi 字符；完整嵌入 JSON 在展开前使用独立 8 MiB UTF-8 字节预算，展开后的字符串仍按原额度检查。临时磁盘预算兼容上传暂存和副本（最多约 280 MiB）、导出 ZIP 的同时存在，并非按小样本无限缩小上传范围。

应用预算之外，UnityPy.load、单次对象读取和完整序列化现在均运行在可丢弃 Linux 子进程（`utils/unity_jobs.py` / `utils/unity_worker.py`）。当前在线导出与回填使用这一边界；卡组和关卡任务已归档。子进程导入 UnityPy 前设置 RLIMIT_AS=384 MiB、CPU=30 秒、FSIZE=140 MiB、NOFILE=64、NPROC=16、CORE=0；父进程每约 50ms 监测 RSS（256 MiB）、实际时间（45 秒）和任务目录（384 MiB，包括上传框架暂存预留）。超限杀死整个子进程组并 wait 回收，失败路径删除工作目录并释放锁。磁盘总量与 RSS 的监测可能有一个采样周期的延迟，地址空间、CPU 与单文件上限由内核执行；主机总磁盘配额仍不由应用提供，慢下载可能保留多个已完成目录。

成功仅返回固定输出文件与大小受限的 JSON 状态；网页进程不接收 Unity 对象图或整份 Bundle bytes。回填通过有限对象遍历，并在写文件前检查输出长度；序列化兼容回退共用同一子进程 CPU/时间预算，内存、递归或 I/O 错误不重试。任务仍串行；锁已忙时立即返回 429。

2026-10-07 真实 card_data_5 补充基线：Bundle 133697 字节，包含 650 张卡牌；TextAsset 原正文 3136648 字符，展开数据 173504 节点、深度 23，展开后最长字符串 136 字符。导出的 JSON 正文 8138620 字节、CSV 正文 3486189 字节，均保留既有单文本、节点、深度和累计预算。JSON/CSV 与 auto/manual 四种组合分别验证无修改回填和真实攻击值修改；补丁文件名匹配兼容负数 path_id。

512 字符名称预算覆盖现有名称和常规 Mod 命名，避免 ZIP 路径由异常长字符串放大。导出与回填共用服务端 TEXT_OBJECT_TYPES，仅支持 MonoBehaviour / TextAsset。

普通上传仍受 150 MiB 请求上限，以及回填的 140 MiB 原文件 / 90 MiB ZIP 文件上限约束；multipart 开销单独预留，原文件槽拒绝直接 ZIP。网页在发送前检查非空文件、各文件大小和合计大小；这不替代服务端限额。日志包含任务动作、结果、耗时及拒绝状态，不记录补丁正文。

安全层负责真实访客 IP、黑名单、可疑请求处理和审计日志。

`utils/json_requests.py` 仅保留 Unity 解包的 141 MiB 请求流上限，以及对应中文 413 响应；全局上传上限仍为 150 MiB。旧关卡 JSON 和卡组表单解析器随工具归档，410 路由不解析旧请求正文。

下载中心保留 `/downloads`，从 `data/downloads.json` 读取唯一 `url`，直接渲染“打开夸克网盘”超链接，无资源目录、下载弹窗或 QQ 群入口，不需要 Vue 或页面脚本。配置校验见 `scripts/validate_downloads.py`。

## 运行约束

- 上传上限为 150 MB。
- Render 配置使用单 worker，避免 UnityPy 并发导致内存峰值过高。
- `data/` 中的 JSON 为运行时配置；编辑器底包已移入 `archive/editors/data/`，当前仅被通用 Unity 测试作为样本读取。
- `data/news.json` 是首页公告来源；`data/version.json` 是版本 API 的首选数据源。

## PVZH DIY 玩家精选
`blueprints/featured.py` 提供两个只读端点：`/api/pvzh-diy/v1/featured/version.json` 和 `manifest.json`。部署时从公开资源仓库 DIY-IMG 的审核目录生成 `data/featured.json`；所有图片 URL 固定 Git 提交 SHA，由 jsDelivr 分发。Render 每次请求仅读取最多 128 KiB 本地快照，不访问 GitHub、不代理图片。两条端点按小型公开 API 精确加入安全层排除列表，其他安全规则不变。无有效快照返回 503，客户端保留上次目录。官方作品独立随客户端发布，不进入服务端目录。

原 `/version`、`/api/version`、`/version.txt` 保留七字段，新增可空 `minimum_supported_version` / `minimum_supported_version_code`。当前均为空，不触发新的最低版本服务限制；旧 force_update 值保留。发布流程和逐件许可详见 [DIY-IMG](https://github.com/Show-o4210/DIY-IMG)。



## 前端依赖与历史兼容

Vue 3.5.13 生产构建与 Tailwind 3.4.17 生成 CSS 提交为本地文件，构建前校验 SHA-256 清单。CSP 的 script-src 仅允许本站，但保留 unsafe-inline/unsafe-eval 以支持既有行内事件与 Vue 模板编译器。Google 字体 CSS/字体仍为外部资源，不加载外部执行脚本。

关卡 JSON 导入和卡组表单输入逻辑已随源码归档，不再公开服务。现行 Node 测试读取 `archive/phantom/static/js/` 快照，保留对历史草稿恢复与 JSON Worker 预算的验证；生产 `static/js/` 不再提供这些文件。
