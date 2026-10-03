# 下载中心维护指南

下载中心展示资料卡片，点击后弹出夸克网盘和 QQ 群入口。每项资料只维护名称、文件类型和图标，不再提供介绍或详情页。

配置集中在 `data/downloads.json`：

```json
{
  "download_options": [
    {
      "id": "quark",
      "name": "夸克网盘",
      "url": "https://pan.quark.cn/s/92d058b77b5f",
      "icon": "cloud_download"
    },
    {
      "id": "qq-group",
      "name": "QQ 群",
      "url": "https://qm.qq.com/q/PayU4f00iQ",
      "icon": "group_add"
    }
  ],
  "items": [
    {"id": "my-tool", "name": "工具名称", "tag": "APK", "icon": "extension"}
  ]
}
```

- `download_options`：所有卡片共用的获取入口，链接只维护一次。
- `items`：扁平资料列表；`id` 和 `name` 必填，`tag` 与 `icon` 可选。
- `id`：稳定的资料标识，不再生成独立页面地址。
- 不再维护分区、介绍、使用步骤、注意事项、版本、日期、封面或逐文件下载链接。

修改后执行 `python scripts/validate_downloads.py`。

验收时检查：每张卡片打开对应名称的弹窗，两个外链正确；关闭按钮、Esc 和点击遮罩均可关闭，关闭后焦点回到卡片。手机上卡片和弹窗不溢出。

详情页及旧下载 API 已移除，sitemap 只收录 `/downloads`。
