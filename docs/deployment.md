# 部署与运维

## Render

仓库的 `render.yaml` 使用 Python 3.12.3，构建命令为：

```text
pip install -r requirements.txt && python scripts/generate_sitemap.py
```

启动命令为：

```text
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --max-requests 500 --max-requests-jitter 50 --access-logfile - --error-logfile -
```

如果 Render Dashboard 中配置了自定义 Build Command 或 Start Command，应与仓库配置保持一致。

## 客户端 IP 的信任边界

当前部署是 Render public Web Service。[Render 官方说明](https://render.com/docs/ddos-protection)其公网服务自动使用 Cloudflare 保护；请求经过 Cloudflare / Render 代理后，Flask 的 `remote_addr` 通常是直接连接的代理地址，不能据此区分所有公网客户端。

[Cloudflare 官方 header 文档](https://developers.cloudflare.com/fundamentals/reference/http-headers/)说明公网入口向源站发送的 `CF-Connecting-IP` 提供连接到 Cloudflare 的客户端地址；已有 `X-Forwarded-For` 会被保留并追加地址，因此不能直接信任左侧值。当前入口模型下使用 Cloudflare 写入的 CF header，不在应用中维护 Cloudflare CIDR 列表或配置 ProxyFix。

唯一规则位于 `security.resolve_client_ip()`：校验并规范化单个 CF IPv4/IPv6；缺失、空值、非法值或逗号地址链时降级到经过同样校验的 `remote_addr`，两者都不可用时使用稳定的 `unknown`。IPv6 压缩并统一大小写，IPv4-mapped IPv6 与 IPv4 使用同一身份。`X-Forwarded-For` 不参与任何身份判定。全局/反馈限流、安全 block/trust、审计去重与记录、反馈 `ua_info.ip` 均使用此规则。`SECURITY_BLOCKED_IPS` / `SECURITY_TRUSTED_IPS` 同样规范化，忽略无效配置项。

信任 CF header 的依据是当前公网代理入口，而不是 IP 字符串合法性本身。若迁移平台、开放直接访问 Gunicorn 的入口、引入私网调用或改变 Cloudflare Worker/代理链，需重新评估 header 的写入/覆盖保证。降级到代理地址会让部分请求共用限流桶，这是保守降级的预期行为。

目前单 worker 保留 `memory://` 限流与进程内审计去重；增加 worker 或实例时，需改为共享限流/去重存储。进程重启也会重置窗口。现有 self-ping 的 UA/Token 识别及其他 UA 策略属于独立问题，本轮没有修改。

## 环境变量

以 `.env.example` 为基准在部署平台配置变量，不要上传真实 `.env`。

- 安全日志需要 `SUPABASE_URL` 与 `SUPABASE_KEY`。
- 自定义域名应设置 `SITE_BASE_URL`，避免 sitemap 继续输出默认域名。
- 如启用进程内自唤醒，`SELF_PING_URL` 必须指向本站 `/health`；可同时设置 `SELF_PING_TOKEN`。

## Supabase

按功能执行：

- `sql/security_logs.sql`：创建安全审计表及写入权限。

后端使用 anon key 时，插入操作不能依赖插入后的 SELECT 回读。安全审计已按 `returning=minimal` 约定处理。

## SEO

- 根路径 `/robots.txt` 与 `/sitemap.xml` 由 `blueprints/home.py` 提供。
- `scripts/generate_sitemap.py` 在构建时同步生成静态版本。
- 新增可公开索引的固定页面时，需要同步检查 `_STATIC_SITEMAP_PAGES` 和生成脚本。
- 新增下载条目后运行 `python scripts/generate_sitemap.py`，并确认详情页 URL 出现在 sitemap 中。

## 上线检查

```powershell
python -m compileall -q .
python scripts/validate_downloads.py
python scripts/generate_sitemap.py
```

部署后至少检查：

- `/health` 返回 200。
- `/robots.txt` 和 `/sitemap.xml` 使用正确公网域名。
- 首页、下载中心和主要编辑器页面可以打开。
- 下载跳转与 GitHub 镜像列表正常。
- 配置 Supabase 后，安全日志写入正常。

