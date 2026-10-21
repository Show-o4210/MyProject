# 下载中心维护

`/downloads` 仅展示一个“打开夸克网盘”超链接，在新标签页打开，无资料列表、下载弹窗或 QQ 群入口；关闭 JavaScript 也可使用。

唯一配置为 `data/downloads.json`：

```json
{"url": "https://pan.quark.cn/s/92d058b77b5f"}
```

更新网盘地址后运行 `python scripts/validate_downloads.py`，检查页面链接指向正确的 HTTPS 分享地址。sitemap 继续收录 `/downloads`。
