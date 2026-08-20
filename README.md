# PVZH Mod 工具箱

一个面向《植物大战僵尸：英雄》（Plants vs. Zombies Heroes）的在线 Mod 辅助工具站，基于 Flask、UnityPy 和 Supabase 开发。

项目目前提供：

- Unity AssetBundle 检查、解包、校验与回填
- 卡组编辑器和关卡编辑器
- 幻影卡牌工坊
- 可扩展的 EA 账号工具工作台（卡牌发送、卡包购买）
- 使用紧凑内容列表，并通过夸克网盘或 QQ 群统一获取资源的下载中心
- 意见反馈、赞助名单、版本查询和基础安全审计

关卡编辑器当前使用 `data/data_assets_43`。程序不会固定依赖某个版本号，而是自动扫描 `data_assets_*`，并选择数字后缀最大的文件；后续更新底包时，直接替换或加入 `data_assets_44`、`data_assets_1000` 等文件即可，打包下载名也会同步更新。

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

EA 账号工具统一入口为 `/ea-tools`。`/card-sender` 与 `/pack-buyer` 仅作为旧链接兼容入口，分别跳转到工作台中的送卡和买包操作；对应业务 API 仍保持独立，便于单独校验和限流。

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
├─ sql/                   # Supabase 建表及权限脚本
└─ docs/                  # 项目维护文档
```

维护关卡编辑器底包时，请保持 `data_assets_<数字版本>` 的命名格式。若 `data/` 中暂时保留多个版本，编辑器会自动使用数字版本最高的一个；非数字后缀文件不会参与选择。

EA/PopCap 请求的 Header、上游调用和响应解析集中在 `logic_ea_api.py`。新增 EA API 业务时，应复用该公共层，并为每个业务保留独立的输入校验与 API 路由；统一页面入口由 `blueprints/ea_tools.py` 和 `templates/ea_tools.html` 承载。

更详细的模块关系见 [架构说明](docs/architecture.md)。下载内容维护见 [下载中心维护指南](docs/downloads.md)，部署与运维见 [部署说明](docs/deployment.md)，历史变更见 [CHANGELOG](docs/CHANGELOG.md)。

## 部署

仓库包含 `render.yaml`。Render 构建阶段会安装依赖并生成 sitemap，运行阶段使用单 Gunicorn worker 与 4 个线程，以适应免费实例的内存限制。部署前请在平台配置环境变量，并执行 `sql/` 中所需的 Supabase 脚本。

详细注意事项见 [docs/deployment.md](docs/deployment.md)。
