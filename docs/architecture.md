# 架构说明

`app.py` 的 `create_app()` 创建一个只读 Flask 应用，注册首页、四类客户端信息接口和旧工具退役响应。应用不启动业务调度器、数据库连接、自唤醒或任何出站请求。限流库仅维护进程内计数及过期清理。

| 组件 | 职责 |
| --- | --- |
| `security.py` | 跨路径的单 IP 与全站总量限流、受信入口 IP 解析 |
| `blueprints/home.py` | 极简调整说明首页、robots 与仅含首页的 sitemap |
| `blueprints/version.py` | DIY 三个版本别名、配置校验及公开无缓存响应 |
| `blueprints/launcher.py` | 启动器版本与公告的有界快照校验 |
| `blueprints/featured.py` | 玩家精选只读目录，不代理图片 |
| `blueprints/sponsors.py` | 保持赞助/鸣谢客户端接口及别名 |
| `blueprints/retired.py` | 旧页面与工具 API 的 410；不读取请求正文 |
| `utils/json_data.py` | 有界本地 JSON 配置读取 |
| `data/` | 四份部署时发布的客户端配置 |
| `templates/`、`static/site.css` | 无 JavaScript 的说明页和退役提示 |

客户端 GET 请求读取本地 JSON 并返回响应，不接收、处理或存储用户上传。GET 自动兼容 HEAD/OPTIONS，客户端数据接口的写入方法返回 405。旧工具路由对常见方法返回 410。不存在公开编辑配置接口。

DIY 版本保留七个原字段和可空的最低支持版本字段。无效或缺失快照返回 JSON 503 与 `VERSION_UNAVAILABLE`，不再回退到过时版本。启动器仍使用 `schema_version=1`、`product=pvzh-launcher`、`channel=stable` 及独立 `release_code`；异常返回 `LAUNCHER_MANIFEST_UNAVAILABLE`。精选目录仍使用 schema 2 和不可变 CDN 地址；赞助接口沿用原兼容行为。所有客户端数据响应继续公开 CORS 与 no-store。

通用 JSON 读取上限为 128 KiB，拒绝重复属性、非有限数字和无效 UTF-8；启动器另保留 64 KiB 输入和响应上限，精选保留 128 KiB 输入上限。构建时 `scripts/validate_snapshots.py` 检查四份真实快照。

前端没有 Vue、Tailwind、外部字体、脚本、表单或浏览器存储。CSP 禁止脚本和第三方资源，允许本站 CSS 和图片。错误响应 no-store，应用正文读取上限 16 KiB；退役端点从不触发正文解析。

移除 UnityPy、任务锁、子进程、ZIP/JSON 补丁处理、Supabase、旧 IP/UA 审计、Flask-Limiter、WhiteNoise 和 APScheduler，但保留轻量请求保护：`limits` 的移动时间窗算法在读取快照前执行，单 IP 默认 10 次/秒、120 次/分钟，所有来源合计 120 次/秒、1200 次/分钟。别名、路径、方法和 User-Agent 共享额度，404/405、静态文件及旧工具 410 请求也计入；只有精确 GET/HEAD `/health` 豁免。全站额度先预检查，再扣单 IP 额度，通过后才扣全站额度，避免一个已超限 IP 用重复拒绝请求耗尽其他用户的全站额度。超限统一返回 JSON 429、Retry-After、no-store 与公开 CORS，不读取快照、不记录数据库事件、不伪装成功。

计数使用单 worker 进程内存，准入判断由锁保护四线程并发。重启会清空计数，增加 worker/实例前必须迁移到共享存储或入口统一限流，不能把进程内限流声称为跨实例防护。默认不信任转发头；仅对 Render 公开受保护入口显式启用 CF-Connecting-IP，校验单 IP 并归一化 IPv6/IPv4-mapped 地址，非法头回退连接来源，不读取 X-Forwarded-For。大流量连接攻击仍需要平台入口防护。参数与部署边界见部署文档。

当前测试覆盖旧客户端接口、真实配置、错误快照、首页、旧工具 410、启动依赖隔离和 SEO。历史工具及其专用测试可在本次转型前的 Git 历史中查看。
