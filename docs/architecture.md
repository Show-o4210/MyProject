# 架构说明

`app.py` 的 `create_app()` 创建一个只读 Flask 应用，注册首页、四类客户端信息接口和旧工具退役响应。导入应用不会启动线程、调度器、数据库连接、自唤醒或任何出站请求。

| 组件 | 职责 |
| --- | --- |
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

不再加载 UnityPy、任务锁、子进程、ZIP/JSON 补丁处理、Supabase、IP/UA 审计、Flask-Limiter、WhiteNoise 或 APScheduler。旧的内存限流与审计去重不再存在；部署平台入口保护仍由平台提供。小型只读服务不再沿用原来针对文件处理的全局访客额度，以免同一网络下的客户端轮询互相挤占额度。

当前测试覆盖旧客户端接口、真实配置、错误快照、首页、旧工具 410、启动依赖隔离和 SEO。历史工具及其专用测试可在本次转型前的 Git 历史中查看。
