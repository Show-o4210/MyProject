# 架构说明

## 应用组成

`app.py` 创建 Flask 应用、加载配置和安全处理器、初始化限流器、注册蓝图，并启动 Render 自唤醒定时任务。静态文件由 WhiteNoise 提供。

主要分层如下：

- `blueprints/`：HTTP 路由、请求解析和页面渲染。
- `services/`：与路由解耦的业务逻辑，目前主要承载反馈提交。
- `logic_*.py`：Unity 底包、关卡和 EA/PopCap API 等领域逻辑。
- `utils/`：卡牌索引、JSON 清洗和数据读取。
- `data/`：运行时配置、下载目录、卡牌数据和 Unity 底包。
- `templates/` 与 `static/`：Jinja2 页面和前端资源。
- `sql/`：Supabase 表结构、RLS 与权限脚本。

## 蓝图与功能

| 模块 | 主要职责 |
| --- | --- |
| `home.py` | 首页、鸣谢页、robots 与动态 sitemap |
| `unity.py` | AssetBundle 检查、解包和回填 |
| `deck_editor.py` | 卡组编辑与打包 |
| `level_editor.py` | 关卡数据读取、编辑与打包 |
| `phantom.py` | 幻影卡牌工坊页面与 API |
| `ea_tools.py` | 统一 EA 账号工具页面 |
| `card_sender.py` | 卡牌发送业务接口与旧地址兼容跳转 |
| `pack_buyer.py` | 卡包购买业务接口、数据接口与旧地址兼容跳转 |
| `downloads.py` | 下载目录、详情、子文件与镜像跳转 |
| `feedback.py` | 反馈页面和提交接口 |
| `version.py` | APK 版本查询接口 |
| `sponsors.py` | 赞助相关接口 |

## EA 账号工具

`/ea-tools` 是面向用户的统一工作台，当前提供卡牌发送和卡包购买两个操作。账号认证与客户端版本设置在页面内共享，但后端继续使用 `/api/send-cards` 和 `/api/buy-pack` 两个独立业务路由，以便分别进行参数校验、限流和错误解释。

两个业务通过 `logic_ea_api.py` 共用 Header 构造、soft purchase 请求和上游响应解析。新增 EA API 功能时，页面操作应加入 `ea_tools.html`，业务参数和 payload 构造应留在独立蓝图或服务中，不应开放允许前端任意提交 payload 的通用代理接口。

旧 `/card-sender` 与 `/pack-buyer` 页面地址保留为兼容跳转，不再维护各自独立模板。

## 关键数据流

卡组、关卡和幻影模块通过 `utils/card_index.py` 读取 `data/index_new.json`。卡组和关卡打包直接修改各自 Unity 底包的 typetree，不经过通用 Unity 工作台的导出格式。

通用 Unity 工作台接收用户上传的 Bundle，支持对象检查、JSON/CSV/PNG 导出、受限补丁回填。Unity 重任务共用 `extensions.py` 中的并发控制，避免低内存实例同时处理多个包。

回填直接提交原 Bundle 和修改 ZIP，不再提供 `/unity/validate-repack`、fast/full 预检或 `require_validate`。结构检查 `/unity/inspect` 仍用于查看 Bundle 内容，与补丁预检无关。正式写入保留 path_id / `_index.json` 匹配、嵌入 JSON 转换和 PPtr 兼容；CSV 标量根据原 typetree 的类型还原。

补丁预算集中于 `utils/patch_limits.py`：ZIP 最多 2048 条目、文件名 512 字符、目录元数据 4 MiB、单成员 32 MiB、累计声明解压大小 128 MiB、每次请求实际读取 64 MiB、压缩比最多 200:1，按最多 64 KiB 分块读取。ZIP 目录尾记录先于 `ZipFile` 构造检查；全部成员元数据先于任何成员正文检查。仅读取用于匹配的索引和实际匹配对象的补丁，不执行 `testzip()`。在线版只支持普通非加密、非分卷、不含 ZIP64 目录的存储/Deflate ZIP。

格式预算：索引 1 MiB，JSON/CSV 各 4 MiB，JSON5 回退解析 256 KiB，PNG 16 MiB；JSON 最多 64 层、100000 节点（解析前另限制结构标记数量），CSV 最多 20000 行、32 列、单字段 131072 字符。图片解码 RGBA 前限制单边 4096、单图总像素 4194304、单次请求图片累计像素 8388608，并保留 Pillow 自身的解压保护。大 JSON5 应转换为标准 JSON；超预算返回中文 413，输入格式错误返回中文 400。失败立即清理临时目录并释放 Unity 锁；成功在下载流关闭后清理。

这些预算限制补丁输入的资源放大，但不能保证 UnityPy 加载压缩 Bundle、构建对象以及 `env.file.save()` 生成完整 bytes 时的峰值内存。普通上传仍受 150 MiB 请求上限，以及回填的 140 MiB 原文件 / 90 MiB ZIP 上限约束；原文件槽拒绝直接 ZIP，避免进入 UnityPy 自动 ZIP 解压。资源受限子进程可以作为将来需要强隔离时的方案，本轮没有引入后台任务或子进程。

反馈由蓝图校验 HTTP 输入，再交给 `services/feedback.py` 写入 Supabase。安全层负责真实访客 IP、黑名单、可疑请求处理和审计日志。

下载中心每次从 `data/downloads.json` 加载内容条目，并将所有非空分区合并为统一列表。资源获取不再使用逐文件 GitHub 镜像，而由根节点 `download_options[]` 统一提供夸克网盘和 QQ 群入口。

## 运行约束

- 上传上限为 150 MB。
- Render 配置使用单 worker，避免 UnityPy 并发导致内存峰值过高。
- `data/` 中的二进制底包和 JSON 都是运行时资产，不应当作普通文档移动。
- `data/news.json` 是首页公告来源；`data/version.json` 是版本 API 的首选数据源。
