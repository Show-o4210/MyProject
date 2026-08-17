# 下载中心维护指南

下载中心采用“内容介绍 + 统一获取入口”的结构：列表中的每个条目只描述一种工具或资源，不再维护逐条文件 URL；所有内容统一通过夸克网盘和 QQ 群提供。

配置保存在 `data/downloads.json`。修改后运行：

```powershell
python scripts/validate_downloads.py
```

## 统一获取方式

根节点 `download_options[]` 控制列表页和详情页展示的入口：

```json
{
  "download_options": [
    {
      "id": "quark",
      "name": "夸克网盘",
      "description": "打开 PVZH 相关内容合集。",
      "url": "https://pan.quark.cn/s/92d058b77b5f",
      "icon": "cloud_download",
      "action": "打开网盘"
    },
    {
      "id": "qq-group",
      "name": "QQ 群",
      "description": "加入群聊获取资源和帮助。",
      "url": "https://qm.qq.com/q/PayU4f00iQ",
      "icon": "group_add",
      "action": "加入群聊"
    }
  ]
}
```

界面默认把第一项作为主要获取方式。旧的 `/api/download/<item_id>` 和 `/api/download/<item_id>/<file_id>` 地址会兼容重定向到第一项，避免已经分享的链接失效。

## 内容条目

条目仍放在 `sections[].items[]` 中，但页面会把所有非空分区合并为一个列表，不展示空分区和分区 Tab。

```json
{
  "id": "my-tool",
  "kind": "single",
  "name": "工具名称",
  "description": "列表页的一行摘要",
  "details": "详情页的完整介绍",
  "usage": ["第一步", "第二步"],
  "notes": ["操作前请备份"],
  "version": "1.0.0",
  "tag": "APK",
  "icon": "extension",
  "size": "15 MB",
  "updated_at": "2026-08-17",
  "images": []
}
```

字段说明：

- `id`：全站唯一的详情页路由标识。
- `name`、`description`：紧凑列表展示的名称和单行摘要。
- `details`：详情页介绍。
- `usage`、`notes`：可选字符串数组。
- `version`、`tag`、`size`、`updated_at`：可选元数据。
- `icon`：Material Symbols 图标名。
- `cover` 或 `images[0]`：可选封面。

不要再给条目添加 `url` 或 `files`。校验脚本发现旧式独立链接时会给出警告。

## 验收

- 手机竖屏下每个条目保持单行小长条布局。
- 点击条目进入详情页，列表不展开大段说明。
- 列表页和详情页均显示夸克网盘、QQ 群两个入口。
- 旧下载 API 能重定向到夸克网盘。
- `scripts/validate_downloads.py` 无错误或警告。
