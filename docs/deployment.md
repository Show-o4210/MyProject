# 部署与运维

本次 PR 仅准备代码，不合并、不部署、不修改 Render Dashboard，也不更改四份客户端配置内容。

## Render 配置

`render.yaml` 保留原服务名 `pvz-h-tools`、Python 3.12.3 与 free 方案，健康检查为 `/health`。

```text
Build: pip install -r requirements.txt && python scripts/validate_snapshots.py
Start: gunicorn app:app --no-control-socket --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 30 --max-requests 500 --max-requests-jitter 50 --access-logfile - --error-logfile -
```

原 Dashboard 曾使用独立的自定义构建命令，不能假定修改 YAML 就会同步生效。上线前确认 Dashboard 的 Build/Start Command 与此文件一致，尤其不能继续运行已删除的前端校验或 sitemap 生成脚本。单 worker 沿用现有配置以控制免费实例开销，不再受 Unity 并发锁约束。

## 环境变量与依赖

只需按情况设置 `SITE_BASE_URL`（默认原 Render 域名）和平台提供的 `PORT`。自定义域名应为完整 HTTPS 站点根地址；首页 canonical、robots、sitemap 均从同一配置生成。`/health` 只检查进程，客户端快照有效性由构建检查及各数据端点确认。

不再读取 `SUPABASE_URL`、`SUPABASE_KEY`、`SECURITY_ADMIN_TOKEN`、`SECURITY_BLOCKED_IPS`、`SECURITY_TRUSTED_IPS`、`SELF_PING_URL` 或 `SELF_PING_TOKEN`。本次不操作线上凭据；上线后可另行清理这些旧环境变量，不要删除其他服务共用的数据库或密钥。

生产直接依赖只有 Flask、Gunicorn 和 python-dotenv；没有 Requests、HTTPX/Supabase 或应用主动出站请求。此前草稿 PR #3 的 Certifi 防护针对旧依赖链，本次已移除该链；本 PR 不合并或关闭 #3，上线时需一起评估其是否仍需保留，勿直接恢复已删除的旧检查指令。

## 可用性变化

原进程内每 14 分钟自唤醒已移除。代码精简不会消除免费服务的休眠、冷启动或平台故障；如版本查询需要常驻响应，应另行选择合适的部署方案，本次不升级套餐、不新增外部保活任务。客户端查询失败应保留已有数据并正常继续使用，不应当成“已是最新版本”。

## 发布及验收

```sh
pip install -r requirements-dev.txt
python scripts/validate_snapshots.py
python -m pytest -q
```

修改 `data/version.json` 发布 DIY 版本；修改 `data/launcher.json` 发布启动器版本和公告。启动器 `release_code` 单独递增，不能与 DIY version_code 或游戏资源编号混用。维护精选目录和赞助配置的方式保持不变。所有修改经审阅和部署后生效，没有线上配置编辑接口。

正式部署后检查：

- `/health` 返回 200，首页显示转型说明、感谢和正确 B 站链接。
- DIY 三个别名及六个赞助/鸣谢别名返回原有字段；启动器、精选版本及精选清单均返回 200、公开 CORS 和 no-store。
- `/unity`、`/downloads`、`/tools` 等旧页面返回 410；向 `/unpack`、`/repack` 提交请求返回 JSON 410。
- robots、sitemap 和首页 canonical 使用正确站点域名，sitemap 仅收录首页。
- 实际客户端的版本、公告、精选和鸣谢加载正常；Web 页面不再展示后两项。

回退时将代码回退到部署前的 Git 提交并恢复对应依赖与启动配置；本次不迁移或删除线上数据库数据。不要用本地测试通过或 Git 推送成功代替正式 HTTPS 与客户端验收。
