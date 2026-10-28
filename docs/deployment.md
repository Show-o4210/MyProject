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

生产直接依赖为 Flask、Gunicorn、python-dotenv 与 limits；没有 Requests、HTTPX/Supabase 或应用主动出站请求。此前草稿 PR #3 的 Certifi 防护针对旧依赖链，本次已移除该链；本 PR 不合并或关闭 #3，上线时需一起评估其是否仍需保留，勿直接恢复已删除的旧检查指令。

## 轻量防刷与入口边界

- `REQUEST_LIMIT_PER_IP` 默认 `10/second;120/minute`；`REQUEST_LIMIT_GLOBAL` 默认 `120/second;1200/minute`。各窗口同时生效，额度跨路径、别名、方法共享，UA 不授予信任。按实际访问量和共享网络用户情况调节，不设置旧的日额度。
- 所有来源合计的额度用于限制准入处理量；单 IP 已超限的重复请求不会消耗其他用户的全站额度。限流在路由/快照读取前执行，拒绝请求返回 JSON 429、数字 Retry-After、no-store 和 CORS；客户端应按重试时间退避，保留已有版本数据，勿立即循环重试。
- 只有精确 GET/HEAD `/health` 豁免，以免攻击导致平台健康检查被误限流。404/405、静态文件和旧工具地址同样计数；不开放管理员/UA 白名单或伪装成功。
- `TRUST_CLOUDFLARE_CLIENT_IP` 在本地/直连默认 false，只用规范化的连接来源地址。Render Blueprint 明确设为 true，以延续原公开代理入口对 CF-Connecting-IP 的使用。**若 Dashboard 自定义配置未自动同步此环境变量，上线前必须核对。** 未开启时所有代理来源可能共享 IP 额度。
- 只有确认全部入口经过可信代理且该代理覆盖此头时才能启用。非法、缺失、多地址或带 zone 的头回退连接来源；不读取任意 X-Forwarded-For。迁移平台、开放直接源站、增加 Worker 或改变代理链时应重新确认此信任边界。全站额度不依赖请求提供的 IP 头。
- 内存计数仅保证当前一个 worker 内四线程共享；重启清空，增加 worker/实例前必须迁移到共享存储或入口统一限流。当前不引入 Redis、数据库或后台审计；limits 会清理内存中的过期额度。
- 应用层限流无法阻止请求抵达 Gunicorn，也不能解决慢连接/带宽耗尽等大流量攻击，需继续使用平台入口保护。

依据：[limits 移动时间窗](https://limits.readthedocs.io/en/stable/strategies.html)、[Render 入口保护](https://render.com/docs/ddos-protection)、[Cloudflare 客户端 IP 头](https://developers.cloudflare.com/fundamentals/reference/http-headers/)。官方资料说明平台代理和头语义，具体入口覆盖保证仍需部署验收，不由 IP 格式合法性证明。

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
- 在受控测试中确认单 IP 跨接口超限为 429、Retry-After 有效，其他 IP 可继续访问，等待窗口后恢复；核对真实代理 IP 解析，不对生产站点发起压力测试。
- DIY 三个别名及六个赞助/鸣谢别名返回原有字段；启动器、精选版本及精选清单均返回 200、公开 CORS 和 no-store。
- `/unity`、`/downloads`、`/tools` 等旧页面返回 410；向 `/unpack`、`/repack` 提交请求返回 JSON 410。
- robots、sitemap 和首页 canonical 使用正确站点域名，sitemap 仅收录首页。
- 实际客户端的版本、公告、精选和鸣谢加载正常；Web 页面不再展示后两项。

回退时将代码回退到部署前的 Git 提交并恢复对应依赖与启动配置；本次不迁移或删除线上数据库数据。不要用本地测试通过或 Git 推送成功代替正式 HTTPS 与客户端验收。
