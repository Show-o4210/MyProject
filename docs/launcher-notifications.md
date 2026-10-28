# 启动器版本与公告

`GET /api/pvzh-launcher/v1/manifest.json` 继续使用部署内的 `data/launcher.json`。本次站点收缩不改变已有版本编号、公告正文、下载地址或客户端合同。DIY 的 `/version` 等接口及 `data/version.json` 继续独立。

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
  "announcements": []
}
```

`release_code` 是独立递增的启动器发布编号，与 DIY APK versionCode、游戏 APK versionCode 或资源清单编号无关。当前真实快照保持 22001，不发布虚假未来版本来测试弹窗。

合同边界沿用现有实现：UTF-8 JSON 输入和成功响应最多 64 KiB；拒绝重复属性、非法数字及无效 Unicode。发布编号为 1～2147483647 整数；公告最多 30 条，ID 唯一，日期有效；标题最多 120 字符、版本名 80 字符、正文/更新说明 8000 字符。下载地址只接受 HTTPS 的原工具站域名或夸克网盘，不代理或自动下载。未识别字段不透传。

配置损坏、缺失或超限返回 503 和 `LAUNCHER_MANIFEST_UNAVAILABLE`。成功和失败响应均保持 no-store 与公开 CORS。只有 GET/HEAD/OPTIONS 可用，写入方法返回 405。服务不访问数据库、不主动请求网络、不接收上传。

客户端每次真正进入启动器检查一次，避免界面重绘造成重复请求。低版本提示更新；网络失败、503 或非法响应不能锁死启动器，也不能伪装成“已是最新版本”。公告只显示为纯文本，不能执行脚本或 HTML。官方社群地址仍由客户端本地受校验配置提供，接口不能替换它。

旧合同允许下载地址指向原站点 `/downloads`，但该网页现在返回 410。当前真实快照已指向夸克网盘；后续发布直接使用有效官方 HTTPS 下载入口，不再把停用页面作为升级入口。

验证：`python scripts/validate_snapshots.py` 和 `python -m pytest -q`。发布后还需在正式 HTTPS 地址和实际启动器中验证公告、低版本提醒与下载入口。
