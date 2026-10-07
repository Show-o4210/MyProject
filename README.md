# PVZH Mod 工具箱

一个面向《植物大战僵尸：英雄》（Plants vs. Zombies Heroes）的在线 Mod 辅助工具站，基于 Flask、UnityPy 和 Supabase 开发。

项目目前提供：

- Unity AssetBundle JSON/CSV 文本导出与补丁回填
- 卡组编辑器和关卡编辑器
- 点击资料卡片，弹出夸克网盘或 QQ 群入口的下载中心
- 赞助名单、版本查询和基础安全审计

关卡编辑器当前使用 `data/data_assets_44`。程序不会固定依赖某个版本号，而是自动扫描 `data_assets_*`，并选择数字后缀最大的文件；后续更新底包时，直接替换或加入 `data_assets_45`、`data_assets_1000` 等文件即可，打包下载名也会同步更新。

## 工具维护 · 2026-10-07

幻影引擎已归档到 `archive/phantom/`，保留源码和草稿兼容逻辑；原页面及 API 返回 HTTP 410。除 Unity 外的工具页面和首页均显示不可关闭的维护公告，可通过现有 QQ 群联系维护者。

Unity 支持真实 `card_data_5`：嵌入 JSON 展开前按 8 MiB UTF-8 字节限制，普通字符串仍保留原 2 Mi 字符限制；CSV 单字段允许 8 Mi 字符，并同步设置 Python CSV 解析器上限。文件名匹配支持负数 path_id。测试样本保存在 `tests/fixtures/card_data_5`，Linux 回归覆盖 JSON/CSV × auto/manual 的无修改回填与真实卡牌数值修改，核对全部卡牌数据及其他对象不变。

## 安全与稳定性更新 · 2026-10-02

本轮围绕五项 Codex Security 发现，完成了 Unity 在线处理、轻量 JSON API、客户端身份和安全审计的针对性修复。设计原则是让安全检查保护服务器，让用户直接完成 Mod 操作，并减少重复处理与长期维护成本。

| 更新方向 | 实际改动 | 用户与维护收益 |
| --- | --- | --- |
| 补丁回填 | 删除深度预检及强制预检交互；ZIP 元数据先检查、成员正文按需分块读取，并累计实际解压字节 | 上传原 Bundle 与修改 ZIP 后直接回填，避免提前执行一次接近完整回填成本的扫描 |
| Bundle 文本导出 | 移除独立结构检查和全对象导出；为读取、文本、输出 ZIP 和临时磁盘设定预算 | 保留常用导出方式，资源超限立即结束任务并返回中文说明 |
| 关卡 API | 独立限制实际 JSON 请求流；严格字段类型；关卡配置采用迭代结构检查，验证完成后才获取 Unity 锁 | 无效输入不占用 Unity 打包锁，常规上传仍保留 150 MiB 全局上限 |
| 客户端身份 | 统一校验与规范化 CF 客户端 IP；非法或缺失时降级到直接连接地址；XFF 不参与安全身份 | 限流、封禁/可信名单与审计保持一致，防止客户端通过修改 XFF 切换身份 |
| 安全审计 | 所有事件按 IP + reason 去重，原子预留窗口；写入失败也保留节流 | 重复封禁请求不再逐次同步写入 Supabase，原有拦截响应保持不变 |

### Mod 操作流程与兼容性

通用 Unity 工作台的回填流程为：**上传原 Bundle → 上传修改后的 ZIP → 直接回填 → 下载修改后的 Bundle**。ZIP 建议来自本站导出结果，或保持正确的 `path_id` / `_index.json` 对应关系；修改前请保留原文件备份。

回填支持 JSON（兼容 JSON5）和 CSV 补丁，处理 MonoBehaviour / TextAsset 文本对象，保留嵌入 JSON 转换、PPtr 兼容、对象匹配与下载流程。深度补丁预检、fast/full 预检与 `require_validate` 已移除；独立的 Bundle 结构检查已移除。解包只需选择 JSON 或 CSV 格式与 auto/manual 文本处理方式，始终附带 `_index.json`；图片导出、贴图回填、DAT/raw 替换和高级对象选择已移除。

输入格式或参数错误返回清楚的中文 400，资源预算超限返回中文 413；Unity 异常路径清理临时文件并释放任务锁，成功下载沿用文件流关闭后的清理。已封禁请求仍保留敏感接口 403、提交类影子封禁和普通页面 404 的既有行为。

### 主要在线资源预算

| 范围 | 默认预算 |
| --- | --- |
| HTTP 上传 | 全局 150 MiB；原 Bundle 140 MiB；回填 ZIP 90 MiB |
| 回填 ZIP | 2,048 条目；文件名 512 字符；目录元数据 4 MiB；单成员声明大小 48 MiB；累计声明解压 128 MiB；压缩比最高 200:1 |
| 回填实际读取 | 每次请求累计 64 MiB；最多 64 KiB 分块读取；同时执行对应格式的单成员预算 |
| 补丁格式 | `_index.json` 10 MiB；JSON / CSV 各 40 MiB；JSON5 回退解析 2,560 KiB |
| 补丁结构 | JSON 64 层 / 500,000 节点；CSV 20,000 行 / 32 列 / 单字段 8,388,608 字符 |
| 导出输入与结构 | 单源对象 16 MiB / 累计源读取 64 MiB；单文本 16 MiB / 累计文本 64 MiB；单对象 500,000 节点 / 累计 2,000,000 节点；深度 32 层 |
| 导出字符串 | 普通字符串 2,097,152 字符；嵌入 JSON 展开前 8 MiB UTF-8 字节 |
| 导出结果 | 5,000 文件 / 未压缩文本 64 MiB / ZIP 32 MiB / 临时磁盘 384 MiB |
| 小型 JSON 请求 | 关卡提取 4 KiB；关卡打包 128 KiB，在 JSON 解析前限制实际请求流 |
| 关卡配置 | 非空对象；32 层；20,000 节点；单字符串 4,096 字符；序列化后 256 KiB UTF-8；`level_id` 为非空字符串、最多 128 字符 |
| 安全审计 | 同 IP + reason 默认 300 秒去重，最低 1 秒 |

完整预算、计数口径和实现说明见 [架构说明](docs/architecture.md)，配置集中在 `utils/patch_limits.py`、`utils/export_limits.py` 和 `utils/json_requests.py`。超出在线预算的大型 Bundle 或补丁建议使用本地工具。

旧版卡片全集兼容：以真实 `card_data_1` 展开的 241,267 个节点为补充基线，回填节点预算调整为 500,000；仅含数组/对象尾逗号的 JSON 补丁可在原有 JSON 预算内解析，字符串正文保持原样，其他 JSON5 语法仍受独立解析上限限制。该调整不放宽总读取或导出预算。

### 验证依据与工程边界

限制以项目实际资源为基线，并为常规 Mod 编辑保留余量：

- 统计 `data_assets_44` 中 1,065 份真实关卡 JSON，无解析失败；原 JSON 最大 9,600 字节，四空格序列化最大 18,474 字节，最大深度 7、节点 988、字符串 56 字符。
- 对 `data_assets_44`、`recipe_decks_1` 和 `recipe_definitions_1` 分别执行JSON 与 CSV，共六次真实导出无失败对象；最大 Bundle 含 2,408 对象，文本导出未压缩内容约 17.4 MiB、ZIP 约 2.0 MiB。
- 回归测试覆盖 JSON / CSV 导出、编辑与回填，移除格式的明确拒绝、声明及实际读取超限、输出预算、临时目录清理、Unity 锁、客户端 IP、限流及审计去重。使用小型文件、调低测试阈值和 mock 验证，不生成真实大型 ZIP bomb，不对线上服务做压力测试。

Unity 解包、回填、卡组导出与关卡打包现运行在可丢弃 Linux 子进程：384 MiB 地址空间硬上限、256 MiB RSS 监测上限、30 秒 CPU / 45 秒实际时间、140 MiB 单文件硬上限；保留已有对象、补丁、ZIP 和临时磁盘预算。超限终止子进程并清理失败输出。单 worker 下全局锁立即拒绝并发任务，避免请求等待占满线程。没有后台队列。

客户端 IP 规则依赖当前 Render public Web Service 的 Cloudflare / Render 公网代理入口；地址格式合法不等于来源可信，迁移部署或开放直连入口时需要重新评估。单 worker 继续使用 `memory://` 限流和进程内审计去重，重启会重置窗口；扩展至多 worker / 多实例时需采用共享存储。UA 不再作为信任凭据；健康检查独立豁免，令牌不得绕过其他业务路径。详见 [部署说明](docs/deployment.md#客户端-ip-的信任边界)。

## 快速开始

建议使用 Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

默认访问地址为 <http://127.0.0.1:5001>。安全日志依赖 Supabase；未配置 Supabase 时，其余不依赖数据库的页面和工具仍可使用。

Windows 下也可以运行 `开始.bat`，但首次运行前仍需安装依赖并配置 `.env`。

## 配置

复制 `.env.example` 为 `.env`，按需填写：

| 变量 | 用途 | 是否必需 |
| --- | --- | --- |
| `SUPABASE_URL` | Supabase 项目地址 | 仅安全日志需要 |
| `SUPABASE_KEY` | Supabase anon key | 仅安全日志需要 |
| `SECURITY_ADMIN_TOKEN` | 查询安全统计接口的鉴权令牌 | 可选 |
| `SECURITY_BLOCKED_IPS` | 额外 IP 黑名单，英文逗号分隔 | 可选 |
| `SECURITY_TRUSTED_IPS` | 可信 IP，英文逗号分隔 | 可选 |
| `SELF_PING_URL` | Render 自唤醒地址，应指向 `/health` | 部署时可选 |
| `SELF_PING_TOKEN` | 自唤醒请求令牌 | 可选 |
| `SITE_BASE_URL` | sitemap 使用的公网根地址 | 自定义域名时建议设置 |

不要提交真实 `.env`、访问令牌或用户凭据。

## 常用维护命令

```powershell
# 检查 Python 语法
python -m compileall -q .

# 执行安全与功能回归测试
python -m unittest discover -s tests -q

# 校验下载中心数据
python scripts/validate_downloads.py

# 重新生成静态 sitemap（Render 构建时也会执行）
python scripts/generate_sitemap.py
```

## 项目结构

```text
MyProject/
├─ app.py                 # Flask 入口、蓝图注册、健康检查和定时自唤醒
├─ blueprints/            # 页面与 API 路由
├─ utils/                 # JSON、卡牌索引等通用工具
├─ templates/             # Jinja2 页面模板
├─ static/                # CSS、JavaScript、图片及静态 SEO 文件
├─ data/                  # 运行时 JSON、卡牌索引和 Unity 底包
├─ scripts/               # 数据校验与 sitemap 生成脚本
├─ tests/                 # 输入预算、Unity 工作流及安全回归测试
├─ sql/                   # Supabase 建表及权限脚本
└─ docs/                  # 项目维护文档
```

维护关卡编辑器底包时，请保持 `data_assets_<数字版本>` 的命名格式。若 `data/` 中暂时保留多个版本，编辑器会自动使用数字版本最高的一个；非数字后缀文件不会参与选择。

更详细的模块关系见 [架构说明](docs/architecture.md)。下载内容维护见 [下载中心维护指南](docs/downloads.md)，部署与运维见 [部署说明](docs/deployment.md)，历史变更见 [CHANGELOG](docs/CHANGELOG.md)。

## 部署

仓库包含 `render.yaml`。Render 构建阶段会安装依赖并生成 sitemap，运行阶段使用单 Gunicorn worker 与 4 个线程，以适应免费实例的内存限制。部署前请在平台配置环境变量，并执行 `sql/` 中所需的 Supabase 脚本。

详细注意事项见 [docs/deployment.md](docs/deployment.md)。
