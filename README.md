# PVZH 版本服务

本项目已由在线 Mod 工具站收缩为只读版本与更新信息服务。Web 工具服务停止，相关工具能力正在逐步迁往 **PVZH Mod 启动器**；迁移尚未完成。开发进度见 [B 站](https://m.bilibili.com/space/1578548705)。

首页 `/` 只提供调整说明与感谢，不展示工具、下载中心、玩家精选或赞助界面。

## 保留的客户端接口

| 内容 | GET 路径 | 配置 |
| --- | --- | --- |
| DIY 版本 | `/version`、`/api/version`、`/version.txt` | `data/version.json` |
| 启动器版本与公告 | `/api/pvzh-launcher/v1/manifest.json` | `data/launcher.json` |
| DIY 玩家精选 | `/api/pvzh-diy/v1/featured/version.json`、`/api/pvzh-diy/v1/featured/manifest.json` | `data/featured.json` |
| 赞助与鸣谢 | `/sponsors`、`/api/sponsors`、`/thanks`、`/api/thanks`、`/sponsors.txt`、`/thanks.txt` | `data/sponsors.json` |

接口沿用既有字段、别名、公开 CORS 与禁止缓存的响应头；DIY 和启动器的版本编号彼此独立。玩家精选和赞助仅保留客户端 API，没有网页展示。本次调整不修改四份配置中的版本、公告或作品数据。DIY 配置损坏或缺失时现返回 503，不再回退到源码里的旧版本。

旧 `/unity`、`/editor`、`/deck-editor`、`/phantom`、`/downloads`、`/tools` 返回 HTTP 410 及说明页；原工具 API 返回 JSON 410，仅读取路由，不解析上传。工具源码、归档底包和专用资源已退出当前树，仍可从 Git 历史找回。完整旧路径见 `blueprints/retired.py`。

## 本地运行与验证

使用 Python 3.12，无需 Node、Linux resource、UnityPy 或 Supabase。

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env
python scripts/validate_snapshots.py
python -m pytest -q
python app.py
```

访问 `http://127.0.0.1:5001`。Windows 激活命令为 `.venv\Scripts\activate`；不再需要 WSL。生产只安装 `requirements.txt`。

## 发布

修改对应 `data/*.json`，运行快照校验和测试，再通过 PR 审阅、合并和部署。没有公共写入接口，不需要数据库或管理令牌。首页文字位于 `templates/index.html`，样式为本地 `static/site.css`，无前端脚本或外部字体。

部署与配置清理见 [部署说明](docs/deployment.md)，组件关系见 [架构说明](docs/architecture.md)，启动器合同见 [通知说明](docs/launcher-notifications.md)。
