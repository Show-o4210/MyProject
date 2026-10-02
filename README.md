# PVZH Mod 工具箱

一个面向《植物大战僵尸：英雄》（Plants vs. Zombies Heroes）的在线 Mod 辅助工具站，基于 Flask、UnityPy 和 Supabase 开发。

项目目前提供：

- Unity AssetBundle 轻量检查、按需导出与补丁回填
- 卡组编辑器和关卡编辑器
- 幻影卡牌工坊
- 可扩展的 EA 账号工具工作台（卡牌发送、卡包购买、账号库存与未开卡包查验）
- 使用紧凑内容列表，并通过夸克网盘或 QQ 群统一获取资源的下载中心
- 意见反馈、赞助名单、版本查询和基础安全审计

关卡编辑器当前使用 `data/data_assets_44`。程序不会固定依赖某个版本号，而是自动扫描 `data_assets_*`，并选择数字后缀最大的文件；后续更新底包时，直接替换或加入 `data_assets_45`、`data_assets_1000` 等文件即可，打包下载名也会同步更新。

## 安全与稳定性更新 · 2026-10-02

本轮围绕五项 Codex Security 发现，完成了 Unity 在线处理、轻量 JSON API、客户端身份和安全审计的针对性修复。设计原则是让安全检查保护服务器，让用户直接完成 Mod 操作，并减少重复处理与长期维护成本。

| 更新方向 | 实际改动 | 用户与维护收益 |
| --- | --- | --- |
| 补丁回填 | 删除深度预检及强制预检交互；ZIP 元数据先检查、成员正文按需分块读取，并累计实际解压字节 | 上传原 Bundle 与修改 ZIP 后直接回填，避免提前执行一次接近完整回填成本的扫描 |
| Bundle 检查与导出 | 检查只保留不读对象正文的轻量模式；取消全对象导出；为读取、文本、图片、输出 ZIP 和临时磁盘设定预算 | 保留常用导出方式，资源超限立即结束任务并返回中文说明 |
| 反馈与关卡 API | 独立限制实际 JSON 请求流；严格字段类型；关卡配置采用迭代结构检查，验证完成后才获取 Unity 锁 | 无效输入不占用 Unity 打包锁，常规上传仍保留 150 MiB 全局上限 |
| 客户端身份 | 统一校验与规范化 CF 客户端 IP；非法或缺失时降级到直接连接地址；XFF 不参与安全身份 | 限流、封禁/可信名单、反馈归属与审计保持一致，防止客户端通过修改 XFF 切换身份 |
| 安全审计 | 所有事件按 IP + reason 去重，原子预留窗口；写入失败也保留节流 | 重复封禁请求不再逐次同步写入 Supabase，原有拦截响应保持不变 |

### Mod 操作流程与兼容性

通用 Unity 工作台的回填流程为：**上传原 Bundle → 上传修改后的 ZIP → 直接回填 → 下载修改后的 Bundle**。ZIP 建议来自本站导出结果，或保持正确的 `path_id` / `_index.json` 对应关系；修改前请保留原文件备份。

回填继续支持当前已有的 JSON / JSON5、CSV、PNG、DAT/raw 补丁，保留嵌入 JSON 转换、PPtr 兼容、对象匹配与下载流程。深度补丁预检、fast/full 预检与 `require_validate` 已移除；独立的 Bundle 轻量检查仍可查看结构，但不提前证明每个对象一定可以导出。正常导出保留推荐、补丁、图片和高级模式，以及 JSON / CSV / PNG 和现有文本处理选项，不再提供无差别的全对象导出。

输入格式或参数错误返回清楚的中文 400，资源预算超限返回中文 413；Unity 异常路径清理临时文件并释放任务锁，成功下载沿用文件流关闭后的清理。已封禁请求仍保留敏感接口 403、提交类影子封禁和普通页面 404 的既有行为。

### 主要在线资源预算

| 范围 | 默认预算 |
| --- | --- |
| HTTP 上传 | 全局 150 MiB；原 Bundle 140 MiB；回填 ZIP 90 MiB |
| 回填 ZIP | 2,048 条目；文件名 512 字符；目录元数据 4 MiB；单成员声明大小 48 MiB；累计声明解压 128 MiB；压缩比最高 200:1 |
| 回填实际读取 | 每次请求累计 64 MiB；最多 64 KiB 分块读取；同时执行对应格式的单成员预算 |
| 补丁格式 | `_index.json` 10 MiB；JSON / CSV 各 40 MiB；JSON5 回退解析 2,560 KiB；PNG 16 MiB；DAT/raw 单成员 32 MiB |
| 补丁结构与图片 | JSON 64 层 / 100,000 节点；CSV 20,000 行 / 32 列 / 单字段 131,072 字符；图片单边 4,096，单图 4,194,304 像素、每次回填累计 8,388,608 像素 |
| 轻量检查 | 10,000 对象；Bundle 内文件 256 个 / 嵌套 16 层；报告 10,000 条目 / 2 MiB；名称最长 512 字符 |
| 导出输入与结构 | 单源对象 16 MiB / 累计源读取 64 MiB；单文本 16 MiB / 累计文本 64 MiB；单对象 500,000 节点 / 累计 2,000,000 节点；深度 32 层 |
| 导出图片与结果 | 单边 4,096；单图 4,194,304 像素 / 累计 16,777,216 像素；单 PNG 16 MiB；5,000 文件 / 未压缩内容 64 MiB / ZIP 32 MiB / 临时磁盘 384 MiB |
| 小型 JSON 请求 | 反馈 16 KiB；关卡提取 4 KiB；关卡打包 128 KiB，在 JSON 解析前限制实际请求流 |
| 关卡配置 | 非空对象；32 层；20,000 节点；单字符串 4,096 字符；序列化后 256 KiB UTF-8；`level_id` 为非空字符串、最多 128 字符 |
| 反馈与审计 | 反馈正文 500 字、联系方式 100 字、每小时 3 次；审计同 IP + reason 默认 300 秒去重，最低 1 秒 |

完整预算、计数口径和实现说明见 [架构说明](docs/architecture.md)，配置集中在 `utils/patch_limits.py`、`utils/export_limits.py` 和 `utils/json_requests.py`。超出在线预算的大型 Bundle、补丁或贴图建议使用本地工具。

### 验证依据与工程边界

限制以项目实际资源为基线，并为常规 Mod 编辑保留余量：

- 统计 `data_assets_44` 中 1,065 份真实关卡 JSON，无解析失败；原 JSON 最大 9,600 字节，四空格序列化最大 18,474 字节，最大深度 7、节点 988、字符串 56 字符。
- 对 `data_assets_44`、`recipe_decks_1` 和 `recipe_definitions_1` 分别执行推荐 JSON 与高级 CSV，共六次真实导出无失败对象；最大 Bundle 含 2,408 对象，推荐导出未压缩内容约 17.4 MiB、ZIP 约 2.0 MiB。
- 完整回归测试 **143 项全部通过**，覆盖正常 JSON / CSV / PNG / DAT 回填、声明及实际读取超限、图片预算、输出预算、临时目录清理、Unity 锁、客户端 IP、限流及审计去重。使用小型文件、调低测试阈值和 mock 验证，不生成真实大型 ZIP bomb，不对线上服务做压力测试。

这些限制约束应用可控制的输入、处理和输出规模，不能硬性隔离 `UnityPy.load()`、单次对象读取、原生图片解码或 `env.file.save()` 生成完整 Bundle bytes 时的内存与 CPU 峰值。若将来需要强隔离，可考虑资源受限子进程；当前保持单 worker 和 Unity 全局任务锁，未引入后台队列、任务状态机或新的调度系统。

客户端 IP 规则依赖当前 Render public Web Service 的 Cloudflare / Render 公网代理入口；地址格式合法不等于来源可信，迁移部署或开放直连入口时需要重新评估。单 worker 继续使用 `memory://` 限流和进程内审计去重，重启会重置窗口；扩展至多 worker / 多实例时需采用共享存储。现有 self-ping UA 识别属于独立待处理问题。详见 [部署说明](docs/deployment.md#客户端-ip-的信任边界)。

## 快速开始

建议使用 Python 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python app.py
```

默认访问地址为 <http://127.0.0.1:5001>。反馈和安全日志依赖 Supabase；未配置 Supabase 时，其余不依赖数据库的页面和工具仍可使用。

EA 账号工具统一入口为 `/ea-tools`，整合了卡牌发送、卡包购买与库存查验三大功能。`/card-sender` 与 `/pack-buyer` 仅作为旧链接兼容入口；卡包列表使用精简规范的 JSON 格式 (`data/packs.json`)。

Windows 下也可以运行 `开始.bat`，但首次运行前仍需安装依赖并配置 `.env`。

## 配置

复制 `.env.example` 为 `.env`，按需填写：

| 变量 | 用途 | 是否必需 |
| --- | --- | --- |
| `SUPABASE_URL` | Supabase 项目地址 | 仅反馈与安全日志需要 |
| `SUPABASE_KEY` | Supabase anon key | 仅反馈与安全日志需要 |
| `SECURITY_ADMIN_TOKEN` | 查询安全统计接口的鉴权令牌 | 可选 |
| `SECURITY_BLOCKED_IPS` | 额外 IP 黑名单，英文逗号分隔 | 可选 |
| `SECURITY_TRUSTED_IPS` | 可信 IP，英文逗号分隔 | 可选 |
| `SELF_PING_URL` | Render 自唤醒地址，应指向 `/health` | 部署时可选 |
| `SELF_PING_TOKEN` | 自唤醒请求令牌 | 可选 |
| `PVZH_*` | EA/PopCap 客户端参数 | 使用送卡或买包功能时可选 |
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
├─ services/              # 可复用业务服务
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

EA/PopCap 请求的 Header、上游调用和响应解析集中在 `logic_ea_api.py`。新增 EA API 业务时，应复用该公共层，并为每个业务保留独立的输入校验与 API 路由；统一页面入口由 `blueprints/ea_tools.py` 和 `templates/ea_tools.html` 承载。

更详细的模块关系见 [架构说明](docs/architecture.md)。下载内容维护见 [下载中心维护指南](docs/downloads.md)，部署与运维见 [部署说明](docs/deployment.md)，历史变更见 [CHANGELOG](docs/CHANGELOG.md)。

## 部署

仓库包含 `render.yaml`。Render 构建阶段会安装依赖并生成 sitemap，运行阶段使用单 Gunicorn worker 与 4 个线程，以适应免费实例的内存限制。部署前请在平台配置环境变量，并执行 `sql/` 中所需的 Supabase 脚本。

详细注意事项见 [docs/deployment.md](docs/deployment.md)。
