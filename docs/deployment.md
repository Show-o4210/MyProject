# 部署与运维

## Render

仓库的 `render.yaml` 使用 Python 3.12.3，构建命令为：

```text
pip install -r requirements.txt && python scripts/verify_frontend.py && python scripts/generate_sitemap.py
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

目前单 worker 保留 `memory://` 限流与进程内审计去重；增加 worker 或实例时，需改为共享限流/去重存储。进程重启也会重置窗口。UA 不再授予信任；令牌仅识别 GET/HEAD /health，不允许绕过其他路径。

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
- 下载中心为单一网盘链接；sitemap 只收录 `/downloads`，不收录归档工具。

## 上线检查

```powershell
python -m compileall -q .
python scripts/validate_downloads.py
python scripts/generate_sitemap.py
```

部署后至少检查：

- `/health` 返回 200。
- `/robots.txt` 和 `/sitemap.xml` 使用正确公网域名。
- 首页、Unity 文本工具和下载中心可以打开。
- 下载中心只有一个夸克网盘超链接，无卡片、弹窗或 QQ 引流。
- `/editor`、`/deck-editor` 及原 API 返回 410。
- 配置 Supabase 后，安全日志写入正常。


## 资源隔离与前端构建

线上处理依赖 Linux resource 内核限制；非 Linux 环境的在线处理明确返回 503，不能悄悄退回网页进程。保持 1 个 Gunicorn worker；增加实例需要共享并发容量与限流存储。RSS/目录监测是采样保护，内核地址空间/CPU/单文件限制提供硬边界；不等同于整个主机磁盘配额。

已提交本地 Vue 和生成 CSS，Render 无需安装 Node。修改 Tailwind 类名后执行 `npm ci && npm run build:css`，检查变化并更新 `static/vendor/manifest.json` 中 CSS SHA-256；构建会拒绝与清单不同的资源。Vue 使用完整生产版以支持原有模板编译器。

测试：`python -m pytest -q`、`node --test tests/frontend/*.test.mjs`、`python scripts/verify_frontend.py`。真实 Unity 测试仅使用仓库底包，不访问生产站点。安全扫描应在修复合并、部署后复查；PR 完成不自动关闭旧扫描 finding。


## eMudhra CA 更新与重建（2026-10）

依据 [Render 官方公告](https://render.com/docs/advisory-emudhra)，原生 Python
服务需要同时刷新系统 CA 和库自带 CA。Requests 与 Supabase 的 HTTPX 依赖使用
Certifi；`requirements.txt` 显式要求 `certifi>=2026.10.19`，防止缓存中的旧版本
在重建时继续满足间接依赖。仓库没有 Python lockfile 或提交的 PEM/CRT CA 包。

当前 Render 构建只运行 pip 和 Python，启动使用 Gunicorn；Vue/CSS 已提交，
不执行 Node.js。无需为此事件修改 Python 3.12.3 或套用 PHP 的专属补丁要求。
如果 Dashboard 覆盖构建命令并加入 npm/Node，则需另按公告更新 Node。

### 部署

1. 合并 CA 依赖更新，确认 Dashboard 的服务、仓库、部署分支及构建命令对应本项目。
2. 检查环境变量是否设置 `REQUESTS_CA_BUNDLE`、`CURL_CA_BUNDLE`、
   `SSL_CERT_FILE`、`SSL_CERT_DIR`，以及 HTTPS 代理。自定义 CA 包必须单独更新；
   不要为了排障禁用证书验证。仓库中没有这类覆盖，但 Dashboard 配置需现场确认。
3. 在服务页面执行 **Manual Deploy > Deploy latest commit**。新 build 更新
   Render 原生系统 CA；仅 Restart 或重新启用旧部署不能替代 build。
   如日志显示旧缓存被复用且 Certifi 未升级，可清除构建缓存后重新部署。
4. 等待部署为 Live，记录 deploy ID、构建时间、commit SHA，并核对安装日志。
   本文是操作步骤，不是已完成部署的记录。

### 在新实例中验证

在 Render Shell 中，使用与 Gunicorn 相同虚拟环境的 Python 执行：

```sh
python -m pip check
python -m pip show certifi requests httpx supabase
python - <<'PY'
import os
import ssl
import certifi
import requests

print("certifi:", certifi.__version__, certifi.where())
assert tuple(map(int, certifi.__version__.split("."))) >= (2026, 10, 19)
print("requests CA:", requests.certs.where())
print("system CA:", ssl.get_default_verify_paths())
for name in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE",
             "SSL_CERT_FILE", "SSL_CERT_DIR"):
    print(name, "set; review bundle separately" if os.getenv(name) else "unset")
PY
```

随后在同一实例、同一环境测试 Requests 和 HTTPX。以下使用无凭据的新客户端，
对应当前 `requests.get()` 和默认 Supabase HTTPX 的 CA 配置；
不要将带有 Supabase API key 的客户端直接请求第三方测试站点。
如以后配置自定义 SSLContext/transport，应改为验证相同配置的无凭据客户端。

```sh
python - <<'PY'
import httpx
import requests

targets = (
    "https://dv-g3b-emudhra.we-have-a-problem.com/",
    "https://dv-g3b-aaa-emudhra.we-have-a-problem.com/",
)
failed = False
with requests.Session() as req, httpx.Client(timeout=15, follow_redirects=False) as hx:
    for name, get in (("requests", req.get), ("httpx", hx.get)):
        # 阳性对照：正常站点必须能完成 TLS。HTTP 状态码不用于判断证书信任。
        try:
            response = get("https://render.com", timeout=15)
            response.close()
            print(name, "control TLS OK")
        except Exception as exc:
            failed = True
            print(name, "control inconclusive:", type(exc).__name__)
        for url in targets:
            try:
                response = get(url, timeout=15)
            except (requests.exceptions.SSLError, httpx.ConnectError) as exc:
                if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                    print(name, url, "certificate rejected")
                else:
                    failed = True
                    print(name, url, "inconclusive:", type(exc).__name__)
            except Exception as exc:
                failed = True
                print(name, url, "inconclusive:", type(exc).__name__)
            else:
                failed = True
                print(name, url, "FAIL: TLS accepted", response.status_code)
                response.close()
raise SystemExit(1 if failed else 0)
PY
```

两个客户端对两个测试端点都应报证书验证错误；任何 HTTP 响应（即使 4xx/5xx）
都表示该次 TLS 已被接受。DNS、超时、拒绝连接不算验证通过。
有 HTTPS 拦截代理时，结果可能只反映代理的信任策略，需再验证实际出站链路。
浏览器或 curl 的结果不能代替 Python 客户端验证，也不能单靠 `/health` 断言修复。

最后确认本站 `/health` 返回 200、自唤醒 Requests 正常、已有业务的 Supabase
安全日志写入正常。保存部署信息、依赖版本和测试结果。Free 套餐若不能使用 Shell，
可在受控的一次性运维任务中执行同样检查并保存日志，不要公开诊断端点。


### 2026-10-29 部署核查记录

已通过 Render 读取「切尔's workspace」中的 `PVZ-H-tools`，服务 ID
`srv-d7f37f1j2pic73922md0`，关联本仓库 `main`，开启按提交自动部署。

- 当前 Live 部署：`dep-dbdo5c142hec739f2hfg`。
- 部署提交：`3356bd06f2324a67befb375656d0321ba26d1e0e`。
- 构建开始：2026-10-23 15:52:16 UTC；上线：15:53:28 UTC
  （北京时间 2026-10-23 23:53:28）。
- 同次构建日志明确包含 `Successfully installed ... certifi-2026.10.23 ...`，
  已高于公告要求的 `2026.10.19`。原生运行时在新 build 时按 Render 公告刷新系统 CA；
  本次没有读取系统 CA 文件或散列。
- Dashboard 实际 Build Command 为 `pip install -r requirements.txt`，
  与上方仓库声明的完整构建命令存在差异；Start Command 与仓库一致，均不调用 Node。
  本次没有修改 Dashboard 构建命令。
- 运行日志含 Requests 自唤醒成功记录。查询部署后日志未命中
  `CERTIFICATE_VERIFY_FAILED` 或 `Failed to log to Supabase`；
  未命中不等于证书拒绝测试通过，也不证明 Supabase 写入成功。

因此，已有部署证据支持本服务已在公告后完成重建并安装修复版 Certifi，
本次无需重复进行紧急重建。显式依赖下限用于保障未来构建。
当前连接没有执行服务内 Python 命令或读取环境变量的能力；
自定义 CA 覆盖、系统 CA 实际内容以及两个测试端点的运行时拒绝结果仍待现场验证。
按上方步骤完成验证；如自定义 CA 仍旧或任一问题证书被接受，再更新相应 CA 并重新构建。
