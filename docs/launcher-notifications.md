# 启动器版本检查与公告

新增公开只读接口 `GET /api/pvzh-launcher/v1/manifest.json`，使用部署内的 `data/launcher.json`，每次请求读取同一快照。它不读取数据库、不发送外部请求、不接收上传、不保存用户状态。Flask 同时按标准支持 HEAD 和 OPTIONS，其他写入方法返回 405。

旧 `/version`、`/version.txt`、`/api/version` 和 `data/version.json` 属于 DIY 客户端，保持独立；`data/news.json` 继续服务工具站首页。

## 响应合同

```json
{
  "schema_version": 1,
  "product": "pvzh-launcher",
  "channel": "stable",
  "latest": {
    "release_code": 22001,
    "version": "R22 RC1",
    "title": "更新标题",
    "notes": "纯文本更新说明",
    "download_url": "https://pan.quark.cn/s/35c024ea8e02"
  },
  "announcements": [
    {
      "id": "20261023-launcher-notices",
      "title": "公告入口已上线",
      "content": "纯文本公告内容",
      "published_at": "2026-10-23"
    }
  ]
}
```

`release_code` 是独立递增的启动器发布编号，与游戏 APK versionCode（当前294）及资源清单编号11056无关。本次为 22001；后续发布必须增加此编号，显示用版本名不可用于数值比较。升级入口为维护者提供的夸克共享链接；安装包以网盘和官方社群实际提供的版本为准。官方社群仍由启动器本地受校验的配置提供，通知接口不能更换该地址。

客户端每次进入启动器检查一次，当前发布编号低于服务端编号就提示更新，不提供“不再提醒”或“下次不显示”。一次进入不因界面重新绘制而重复请求或叠加多个弹窗。网络失败、503、非法响应不应锁死启动器，也不能把失败显示成“已是最新版本”。公告正文以文本显示，不执行 HTML、JavaScript、Mod 或游戏文件。

## 配置边界

- UTF-8 JSON 总大小最多 65536 字节；拒绝无效 UTF-8、重复 JSON 属性、尾随 JSON、NaN/Infinity。
- 顶层产品、频道、合同版本固定；版本号是 1～2147483647 的整数，拒绝布尔值、浮点数及字符串。
- 公告最多 30 条，可以为空；ID 是 1～80 字符的英文字母、数字、点、下划线、连字符且唯一；首字符必须为字母或数字。
- 标题最多 120 字符，版本名最多 80 字符，更新说明/正文最多 8000 字符。正文和更新说明允许换行、回车、制表符；拒绝替代字符、未配对代理码点和其他控制字符。
- 日期使用有效 `YYYY-MM-DD`。下载地址最多 4096 字符，仅允许 `https://pvz-h-tools.onrender.com` 或 `https://pan.quark.cn`，不能带用户信息、片段、空白、反斜杠或非 443 端口；不做代理、不自动下载。
- 未识别字段不透传；配置缺失、损坏、过大或不符合合同时返回 HTTP 503 和 `LAUNCHER_MANIFEST_UNAVAILABLE`，不泄露文件路径/异常内容，不伪装空公告成功。
- 成功和 503 响应均使用 `no-cache, no-store, must-revalidate`、`Pragma: no-cache`、`Expires: 0`，沿用公开接口 CORS。
- 成功响应使用紧凑 UTF-8 JSON，并再次检查实际响应体不超过 65536 字节，避免 Flask 默认的中文 ASCII 转义令响应超出 Android 端读取上限；不改变全站 JSON provider 或旧接口。

## 接入与维护

Blueprint 已由 `app.py` 导入和注册，接口精确列入 `security.py` 的公开路径名单。此名单只绕过业务页 UA 审计，仍受全局每天 2000 次/每小时 400 次的限流；建议客户端发送 `Accept: application/json` 和自己的 User-Agent。

更新公告或版本时只改 `data/launcher.json`，完整部署后生效。不新增公共修改接口，不需要 Supabase、管理员密钥、额外 Python 包或 Render 配置调整。不要把真实凭证放入 JSON、示例、测试或日志。

本地测试不导入完整 `app.py`，避免启动 APScheduler 和访问线上服务：

```text
python -m unittest discover -s tests -p test_launcher_notifications.py -v
```

部署后通过正式 URL `https://pvz-h-tools.onrender.com/api/pvzh-launcher/v1/manifest.json` 检查 HTTP 200、合同字段和 no-store，再确认旧 DIY 版本接口仍返回原有版本数据。客户端上线验收应直接请求正式 HTTPS，检查公告和每次真正进入前台的低版本提醒。不要以本地测试或Git推送成功代替线上验收。

当前正式发布编号保持22001。隔离的低版本验收客户端使用22000及同一正式接口；不向所有用户发布虚假的未来版本。升级弹窗提供夸克网盘与官方社群，关闭只作用于本次进入。
