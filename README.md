# PVZH Mod 工具箱

面向《植物大战僵尸：英雄》的在线 Mod 辅助工具站，基于 Flask、UnityPy 和 Supabase。

当前提供：

- Unity AssetBundle 的 JSON/CSV 文本导出、修改 ZIP 回填与 Bundle 下载。
- 下载中心：一个直接打开夸克网盘的超链接。
- 首页公告、鸣谢、赞助信息、客户端版本查询和 DIY 玩家精选目录。

## 工具归档 · 2026-10-21

关卡与卡组工具已正式归档到 `archive/editors/`，幻影引擎位于 `archive/phantom/`。旧页面及原 API 返回 HTTP 410，不清除浏览器历史数据。首页、导航和 sitemap 不再提供这些工具入口，应用启动不加载编辑器实现或数据。

下载中心保留 `/downloads` 地址，只提供现有夸克网盘链接；资料卡片、下载弹窗和 QQ 引流已移除，旧维护公告已撤下。

## Unity 文本工具

解包支持 JSON/CSV 与 auto/manual 文本处理，导出 MonoBehaviour / TextAsset，附带 `_index.json` 和摘要。回填流程：上传原 Bundle → 上传修改 ZIP → 直接回填 → 下载修改 Bundle。

保留 JSON5、尾逗号、嵌入 JSON、负数 path_id、索引匹配和 PPtr 兼容。只支持文本补丁，不提供图片、raw/DAT 替换、独立结构检查或深度预检。

Unity 重任务运行在受限 Linux 子进程，并由全局锁串行执行；非 Linux 环境返回 503。资源预算、临时文件清理、限流和安全审计保持启用，详见 [架构说明](docs/architecture.md)。

## 快速开始

使用 Python 3.12；完整 Unity 功能需要 Linux（Windows 开发可使用 WSL）。

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python app.py
```

默认访问 `http://127.0.0.1:5001`。Windows 可以安装依赖后使用 `开始.bat` 查看页面与非 Unity 接口，但无法执行 Unity 子进程任务。

安全日志需要 `SUPABASE_URL` / `SUPABASE_KEY`；未配置时其他不依赖数据库的功能仍可使用。管理员令牌、IP 名单、自唤醒及域名配置见 `.env.example` 和 [部署说明](docs/deployment.md)。不要提交真实 `.env` 或凭据。

## 项目结构

```text
app.py                 Flask 入口、健康检查和定时保活
blueprints/            当前页面/API，以及归档工具的轻量 410 路由
templates/             Jinja2 页面；Unity 页面使用 Vue
static/、styles/       前端资源、Vue 与 Tailwind
utils/                 Unity 子进程、输入/输出预算和 JSON 工具
data/                  公告、版本、赞助、下载链接与精选目录配置
security.py            客户端 IP、访问检查与审计
database.py、sql/      Supabase 客户端与安全日志表
archive/editors/       关卡/卡组源码、专用数据、底包与历史测试
archive/phantom/       幻影引擎源码与资源
tests/、scripts/       当前回归测试及维护脚本
docs/                  架构、部署、下载维护与变更记录
```

## 验证与部署

在 Linux 环境运行：

```sh
python -m pip install pytest
python -m pytest -q
node --test tests/frontend/*.test.mjs
python scripts/validate_downloads.py
python scripts/verify_frontend.py
python scripts/generate_sitemap.py
```

前端历史 JSON/草稿兼容测试读取归档快照；关卡/卡组专用测试已随源码归档，不属于当前 CI。通用 Unity 测试仍使用归档底包作为真实回归样本。

Render 构建与启动配置见 `render.yaml`：Python 3.12.3，单 Gunicorn worker、4 个线程。依赖 Vue 3.5.13 与 Tailwind 3.4.17 已作为本地静态文件提交；改动样式时按 [部署说明](docs/deployment.md) 构建并更新校验清单。
