# 正式启动器发行合同

`GET /api/pvzh-launcher/v2/manifest.json` 为正式启动器单独提供发行信息。路径为 v2，wire 仍是 `schema_version=1`、`product=pvzh-launcher`、`channel=stable`、`latest` 和 `announcements`。`latest` 仅含原合同五字段：`release_code`、`version`、`title`、`notes`、`download_url`。

发行身份唯一来源是客户端发行目录的 `release.json`，部署时原字节复制为 `data/launcher-release.json`。该内部文件精确包含十字段，不接收未知字段：

| 字段 | 规则／映射 |
| --- | --- |
| schema_version／product | 精确整数1／pvzh-launcher |
| public_version | `v1`、`v1.1`、`v1.0.1`等最多三段正主版本，子版本允许0，无前导0，最多80码点；映射为latest.version |
| release_code | 1～2147483647整数，不接受布尔／小数；映射为latest.release_code |
| internal_revision | R加正整数，无前导0，最多80码点；内部校验，不额外输出 |
| channel | 精确stable |
| release_date | 有效规范YYYY-MM-DD；内部校验，不额外输出 |
| title／notes | 标题非空白且最多120码点；说明允许空或换行，最多8000码点；对应latest字段 |
| download_url | 最多4096码点，仅HTTPS的pan.quark.cn或pvz-h-tools.onrender.com；无凭据、片段、反斜杠、空白，端口缺省或443 |

当前身份是对外 `v1`、内部 `R51`、`release_code=100001`、stable、`2026-10-30`。发布编号独立单调递增，不与游戏Android versionCode、DIY编号、资源版本或R编号换算。服务仅验证范围，不保存历史最大值；维护者在发布审阅中检查递增。开发／R构建默认development，正式包须显式stable。关闭正式升级提示、标签、按钮及缓存绕过的策略在客户端执行，服务器不根据UA或参数猜测客户端模式。

普通公告唯一来源仍是 `data/launcher.json` 的 `announcements`；更新公告只改这一处。新接口不采用旧文件的 `latest`。公告沿用唯一ID、最多30条、标题120码点、正文8000码点及有效日期的校验；未知字段不透传。历史 `/api/pvzh-launcher/v1/manifest.json` 的旧latest和正文、DIY `/version`、项目名单、精选与赞助配置均保持，防止历史R客户端收到正式版升级。

两份输入各最多64KiB，UTF-8成功响应合成后也最多64KiB；拒绝重复键、非有限数字、非法UTF-8、替换字符／孤立代理项以及字段中的非法控制字符。文件缺失、损坏、超限返回JSON503及 `LAUNCHER_MANIFEST_UNAVAILABLE`，不回退为成功或改动旧接口。没有写入、编辑、上传、数据库或主动联网。

GET／HEAD读取快照，HEAD无正文；OPTIONS无需读取配置。POST／PUT／PATCH／DELETE为405。成功、503、405与429保留公开CORS及no-store，沿用全局跨路由限流。新接口不会豁免请求保护。

发布前运行 `python scripts/validate_snapshots.py` 和 `python -m pytest -q`，确认发行文件与客户端原件同SHA、旧配置未改。经审阅合并和部署后，再单独记录正式HTTPS与实际客户端验收；本机Flask测试不证明Android UI或线上已生效。
