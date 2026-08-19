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
| `unity.py` | AssetBundle 检查、解包、预检和回填 |
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

通用 Unity 工作台接收用户上传的 Bundle，支持对象检查、JSON/CSV/PNG 导出、补丁预检和回填。Unity 重任务共用 `extensions.py` 中的并发控制，避免低内存实例同时处理多个包。

反馈由蓝图校验 HTTP 输入，再交给 `services/feedback.py` 写入 Supabase。安全层负责真实访客 IP、黑名单、可疑请求处理和审计日志。

下载中心每次从 `data/downloads.json` 加载内容条目，并将所有非空分区合并为统一列表。资源获取不再使用逐文件 GitHub 镜像，而由根节点 `download_options[]` 统一提供夸克网盘和 QQ 群入口。

## 运行约束

- 上传上限为 150 MB。
- Render 配置使用单 worker，避免 UnityPy 并发导致内存峰值过高。
- `data/` 中的二进制底包和 JSON 都是运行时资产，不应当作普通文档移动。
- `data/news.json` 是首页公告来源；`data/version.json` 是版本 API 的首选数据源。
