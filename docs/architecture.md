# 架构说明

## 应用组成

`app.py` 创建 Flask 应用、加载配置和安全处理器、初始化限流器、注册蓝图，并启动 Render 自唤醒定时任务。静态文件由 WhiteNoise 提供。

主要分层如下：

- `blueprints/`：HTTP 路由、请求解析和页面渲染。
- `logic_*.py`：Unity 底包和关卡等领域逻辑。
- `utils/`：卡牌索引、JSON 清洗和数据读取。
- `data/`：运行时配置、下载目录、卡牌数据和 Unity 底包。
- `templates/` 与 `static/`：Jinja2 页面和前端资源。
- `sql/`：Supabase 表结构、RLS 与权限脚本。

## 蓝图与功能

| 模块 | 主要职责 |
| --- | --- |
| `home.py` | 首页、鸣谢页、robots 与动态 sitemap |
| `unity.py` | AssetBundle 文本解包和回填 |
| `deck_editor.py` | 卡组编辑与打包 |
| `level_editor.py` | 关卡数据读取、编辑与打包 |
| `phantom.py` | 幻影卡牌工坊页面与 API |
| `downloads.py` | 资料卡片列表与共享获取入口 |
| `version.py` | APK 版本查询接口 |
| `sponsors.py` | 赞助相关接口 |

## 关键数据流

卡组、关卡和幻影模块通过 `utils/card_index.py` 读取 `data/index_new.json`。卡组和关卡打包直接修改各自 Unity 底包的 typetree，不经过通用 Unity 工作台的导出格式。

Unity 页面使用解包 / 回填双页签，JSON/CSV 直接选择，auto/manual 兼容选项默认折叠；任务处理中锁定表单与页签，错误和下载状态分别显示在所属表单。通用 Unity 工作台接收用户上传的 Bundle，支持 JSON/CSV 文本导出、受限补丁回填。Unity 重任务共用 `extensions.py` 中的并发控制，避免低内存实例同时处理多个包。

回填直接提交原 Bundle 和修改 ZIP，不再提供 `/unity/validate-repack`、fast/full 预检或 `require_validate`。独立结构检查及 `/unity/inspect` 接口已移除。正式写入保留 path_id / `_index.json` 匹配、嵌入 JSON 转换和 PPtr 兼容；CSV 标量根据原 typetree 的类型还原。

补丁预算集中于 `utils/patch_limits.py`：ZIP 最多 2048 条目、文件名 512 字符、目录元数据 4 MiB、单成员 48 MiB、累计声明解压大小 128 MiB、每次请求实际读取 64 MiB、压缩比最多 200:1，按最多 64 KiB 分块读取。ZIP 目录尾记录先于 `ZipFile` 构造检查；全部成员元数据先于任何成员正文检查。仅读取用于匹配的索引和实际匹配对象的补丁，不执行 `testzip()`。在线版只支持普通非加密、非分卷、不含 ZIP64 目录的存储/Deflate ZIP。

格式预算：索引 10 MiB，JSON/CSV 各 40 MiB，JSON5 回退解析 2560 KiB；JSON 最多 64 层、500000 节点（解析前另限制结构标记数量），CSV 最多 20000 行、32 列、单字段 131072 字符。大 JSON5 应转换为标准 JSON；超预算返回中文 413，输入格式错误返回中文 400。失败立即清理临时目录并释放 Unity 锁；成功在下载流关闭后清理。

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

JSON 和 CSV 的六次真实导出均无失败对象；CSV 最大未压缩 8137380 字节、ZIP 1807441 字节。单对象展开 JSON 最大 7095592 字节；data_assets_44 的单对象 JSON P50/P95 为 1431/5912 字节，另外两个包的 P50 为 3130/887 字节。最大源对象 1143932 字节；最大单对象结构 297329 节点、深度 10，最大请求累计 792369 节点、读取源数据 5306540 字节。对象预算约最大实例的 4.15 倍、输出文件 2.08 倍、单文本 2.36 倍、累计内容 3.67 倍、ZIP 15.9 倍；16 MiB 源对象预算约 14.7 倍，64 MiB 累计源读取约 12.6 倍；单结构节点 1.68 倍、累计节点 2.52 倍、深度 3.2 倍。展开前 TextAsset 可能包含约 1.14 MiB 的完整 JSON 字符串，因此单字符串预算为 2 Mi 字符，而非按展开后小字符串设置。临时磁盘预算兼容上传暂存和副本（最多约 280 MiB）、导出 ZIP 的同时存在，并非按小样本无限缩小上传范围。

应用预算不能中断 UnityPy.load 或单次 read/read_typetree 的库内部 CPU/RAM 峰值；源元数据预算和返回结构检查不是硬内存隔离。磁盘预算是单请求的应用计数，不是主机总配额，长时间并行下载也可能保留多个目录。若将来必须强隔离，仍需资源受限子进程及系统内存、时间、磁盘限制；当前未引入子进程、worker 或队列。

512 字符名称预算覆盖现有名称和常规 Mod 命名，避免 ZIP 路径由异常长字符串放大。导出与回填共用服务端 TEXT_OBJECT_TYPES，仅支持 MonoBehaviour / TextAsset。

这些预算限制补丁输入的资源放大，但不能保证 UnityPy 加载压缩 Bundle、构建对象以及 `env.file.save()` 生成完整 bytes 时的峰值内存。普通上传仍受 150 MiB 请求上限，以及回填的 140 MiB 原文件 / 90 MiB ZIP 上限约束；原文件槽拒绝直接 ZIP，避免进入 UnityPy 自动 ZIP 解压。资源受限子进程可以作为将来需要强隔离时的方案，本轮没有引入后台任务或子进程。

安全层负责真实访客 IP、黑名单、可疑请求处理和审计日志。

小型 JSON 请求预算集中于 `utils/json_requests.py`，依赖 Flask >= 3.1 的每请求 `max_content_length`，在读取正文前设置。`POST /api/editor/ab/extract` 上限 4 KiB；`POST /api/editor/ab/pack` 上限 128 KiB，不降低全局 150 MiB 上传上限。Content-Length 仅作辅助拒绝，实际读取使用 Werkzeug 受限流。WSGI 服务器标记 `wsgi.input_terminated` 的流达到预算即返回中文 413（恰好等于预算也保守拒绝），避免把 `readall()` 返回的截断正文当作完整 JSON；未标记终止且没有 Content-Length 时遵循 Werkzeug 的安全空流行为。已封禁请求仍保留安全层的提前响应。

关卡 config 必须是非空对象：根深度为 1，最多 32 层、20000 节点（键和值均计数）、单个键或字符串值 4096 字符、保持原四空格缩进后最多 256 KiB UTF-8；level_id 为非空字符串、最长 128 字符。遍历使用迭代器栈，序列化分段计数；超预算中文 413，参数或 JSON 格式错误中文 400。请求体解析、参数/结构预算和序列化均先于 Unity 锁；目标查找与写入共用一次 UnityPy.load。异常释放锁并清理目录，成功在下载流关闭后清理。UnityPy 加载与完整 Bundle 输出的峰值内存风险仍见上文。

默认预算基线：2026-10-02 随项目提供的 `data/data_assets_44` 中含 PlayerConfig / BoardConfig 的 1065 份 TextAsset 关卡 JSON，统计无解析失败。下表分位数取排序后向下取整的位置；字符串长度包含对象键，节点包含对象键和值。

| 指标 | 最小 | P50 | P95 | 最大 | 默认预算 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 原 JSON UTF-8 字节 | 2191 | 2553 | 2892 | 9600 | pack 请求 131072 字节（含参数） |
| 四空格序列化 UTF-8 字节 | 4068 | 4767 | 5446 | 18474 | 262144 字节 |
| 深度 | 6 | 7 | 7 | 7 | 32 |
| 节点 | 216 | 252 | 288 | 988 | 20000 |
| 最长字符串字符数 | 36 | 42 | 45 | 56 | 4096 |

最大原/序列化 JSON 与最多节点均来自 FTUE_Node_1_Slim，现有 level_id 最长 39 字符。pack 正文约为最大原 JSON 的 13.7 倍，序列化预算约 14.2 倍、节点约 20 倍，留出 Mod 编辑余量。

下载中心从 `data/downloads.json` 的 `items[]` 加载资料卡片；点击卡片打开原生 dialog，共享 `download_options[]` 中的夸克网盘和 QQ 群链接。只维护名称、文件类型与图标；详情页、独立下载 API 和分区结构已移除，sitemap 仅收录下载中心。

## 运行约束

- 上传上限为 150 MB。
- Render 配置使用单 worker，避免 UnityPy 并发导致内存峰值过高。
- `data/` 中的二进制底包和 JSON 都是运行时资产，不应当作普通文档移动。
- `data/news.json` 是首页公告来源；`data/version.json` 是版本 API 的首选数据源。

## PVZH DIY 玩家精选
`blueprints/featured.py` 提供两个只读端点：`/api/pvzh-diy/v1/featured/version.json` 和 `manifest.json`。部署时从公开资源仓库 DIY-IMG 的审核目录生成 `data/featured.json`；所有图片 URL 固定 Git 提交 SHA，由 jsDelivr 分发。Render 每次请求仅读取最多 128 KiB 本地快照，不访问 GitHub、不代理图片。两条端点按小型公开 API 精确加入安全层排除列表，其他安全规则不变。无有效快照返回 503，客户端保留上次目录。官方作品独立随客户端发布，不进入服务端目录。

原 `/version`、`/api/version`、`/version.txt` 保留七字段，新增可空 `minimum_supported_version` / `minimum_supported_version_code`。当前均为空，不触发新的最低版本服务限制；旧 force_update 值保留。发布流程和逐件许可详见 [DIY-IMG](https://github.com/Show-o4210/DIY-IMG)。

