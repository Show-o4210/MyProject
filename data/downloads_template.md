## 一、快速复制模版

在 `data/downloads.json` 的相应 `sections` -> `items` 数组中，您可以直接复制以下模版并根据需要修改。

### 1. 单文件下载模版 (`single`)

适用于只有一个主文件可供下载的资源（如 APK 工具、单个 ZIP 压缩包等）。

```json
{
  "id": "my-single-tool",
  "kind": "single",
  "name": "这里填写资源名称",
  "description": "这里填写简短的一句话介绍（显示在列表页）。",
  "details": "这里填写详细的内容介绍（支持使用 \\n 换行，显示在详情页中）。",
  "usage": [
    "第一步：下载并安装/解压本资源",
    "第二步：根据说明放入游戏指定目录",
    "第三步：启动游戏确认生效"
  ],
  "notes": [
    "注意事项1：请提前备份原文件以免丢失。",
    "注意事项2：需要特定的环境或 Root 权限（如适用）。"
  ],
  "version": "1.0.0",
  "tag": "ZIP",
  "icon": "folder_zip",
  "size": "15 MB",
  "url": "https://download.link/file.zip",
  "updated_at": "2026-07-12",
  "images": [
    "/static/images/download/preview_1.png"
  ]
}
```

### 2. 多文件/合集下载模版 (`bundle`)

适用于包含多个子文件（如完整版、分卷、底包、不同平台的版本等）的作品集。

```json
{
  "id": "my-bundle-mod",
  "kind": "bundle",
  "name": "这里填写合集作品名称",
  "description": "这里填写合集作品的简短介绍（显示在列表页）。",
  "details": "这里填写该合集作品的详细说明（显示在详情页中，支持 \\n 换行）。",
  "usage": [
    "第一步：进入文件列表，下载标有「推荐」的完整包，或单独下载您需要的分卷",
    "第二步：将下载的文件解压或移动到指定文件夹"
  ],
  "notes": [
    "注意：合集内的分卷可以组合使用或单独使用。"
  ],
  "version": "v2.1",
  "tag": "合集",
  "icon": "folder_zip",
  "size": "多文件",
  "updated_at": "2026-07-12",
  "series_id": "optional-series-id",
  "series_name": "可选系列名称",
  "series_order": 1,
  "images": [
    "/static/images/download/preview_1.png",
    "/static/images/download/preview_2.png"
  ],
  "files": [
    {
      "id": "full-pack",
      "name": "完整安装包（推荐）",
      "description": "一键包含全部内容的完整压缩包。",
      "size": "150 MB",
      "tag": "ZIP",
      "recommended": true,
      "updated_at": "2026-07-12",
      "url": "https://download.link/full.zip",
      "notes": [
        "包含最新补丁，推荐首次下载的用户使用。"
      ]
    },
    {
      "id": "part-a",
      "name": "分卷 A - 基础材质包",
      "description": "只包含基础素材与贴图。",
      "size": "80 MB",
      "tag": "ZIP",
      "recommended": false,
      "updated_at": "2026-07-12",
      "url": "https://download.link/partA.zip"
    }
  ]
}
```

---

## 二、属性字段详解

### 1. 基础字段（通用）

| 键名 (Key) | 类型 | 必填 | 说明 | 示例 |
| :--- | :--- | :--- | :--- | :--- |
| `id` | String | **是** | 资源的唯一标识符，不能重复。用于路由（URL），如 `/downloads/my-tool`。 | `"pvzh-DIY"` |
| `kind` | String | **是** | 资源形态。只能填 `"single"` (单文件) 或 `"bundle"` (多文件合集)。 | `"single"` / `"bundle"` |
| `name` | String | **是** | 资源的显示名称。 | `"PVZH卡牌DIY v2.0"` |
| `description`| String | 否 | 简短描述，展示在下载中心的列表卡片上。建议控制在 2-3 行以内。 | `"用于 PVZH 卡牌内容编辑与 DIY 制作。"` |
| `details` | String | 否 | 详细介绍，展示在详情页的内容介绍版块中。支持用 `\n` 进行换行。 | `"这是详细的工具介绍... \n 可以支持多行展示"` |
| `version` | String | 否 | 版本号。 | `"2.0"`, `"v1.0-beta"` |
| `tag` | String | 否 | 格式标签，会渲染在标题旁边的药丸形标签中。 | `"APK"`, `"ZIP"`, `"贴图"` |
| `size` | String | 否 | 文件大小。 | `"37 MB"`, `"2 KB"`, `"多文件"` |
| `updated_at` | String | 否 | 更新时间，建议使用 `YYYY-MM-DD` 格式。 | `"2026-07-12"` |
| `images` | Array | 否 | 预览图片地址数组（支持本地绝对路径或外链），会显示在图片预览区域。 | `["/static/images/download/自制卡.png"]` |

### 2. 交互与说明字段

* **`usage` (Array of Strings)**: 步骤式指南。将在详情页中渲染为带序号（1, 2, 3...）的步骤列表。
* **`notes` (Array of Strings)**: 注意事项。将在详情页中渲染为黄色的警告/提示框。
* **`icon` (String)**: 图标名称（若未设置封面图，会以小图标展示）。使用 [Material Symbols](https://fonts.google.com/icons) 字体图标名称：
  * 压缩包: `"folder_zip"`
  * 普通工具: `"build"`
  * 图片/贴图: `"image"`
  * 替换/修改: `"swap_horiz"`
  * 通用箱子: `"inventory_2"`

### 3. 系列/关联字段 (可选)

如果多个下载项同属一个系列（例如同一 Mod 的不同章节，或同一系列工具的配套资源），可以配置它们以便在详情页底部互相跳转。

* **`series_id` (String)**: 系列的唯一标识符。相同 `series_id` 的资源会作为“同系列其它作品”渲染在右下角。
* **`series_name` (String)**: 系列的显示名称。
* **`series_order` (Integer)**: 在系列中的排序顺序（升序）。

### 4. 仅用于合集 (`bundle`) 内部文件列表 (`files`)

当 `"kind": "bundle"` 时，需要在最外层添加一个 `files` 字段，其包含若干子文件对象：

| 子文件键名 | 类型 | 必填 | 说明 |
| :--- | :--- | :--- | :--- |
| `id` | String | **是** | 子文件在当前合集内的唯一 ID。下载 API 路由会用到：`/api/download/<item_id>/<file_id>`。 |
| `name` | String | **是** | 子文件名（例如 `"完整包"`, `"底包"` 等）。 |
| `url` | String | **是** | 该子文件的实际下载链接。 |
| `description`| String | 否 | 子文件的一句话描述。 |
| `size` | String | 否 | 子文件的大小。 |
| `tag` | String | 否 | 子文件的格式标签（如 `"ZIP"`, `"APK"`）。 |
| `recommended`| Boolean| 否 | 是否推荐。如果为 `true`，会在列表里置顶并带有高亮“推荐”标识。同时若主项未提供 `url`，该子文件的 `url` 将作为主按钮的默认下载链接。 |
| `updated_at` | String | 否 | 子文件的更新日期。 |
| `notes` | Array | 否 | 子文件专属的小提示，会以小感叹号图标显示在子文件下方。 |

---

## 三、如何添加新板块/分类 (Sections)

在 `data/downloads.json` 的根节点 `sections` 数组中，目前已存在：

1. `mods` (Mod 内容)
2. `tools` (工具与资源)

如果您想增加第三个分区（例如“视频教程”或“自制素材”），可以像下面这样追加一个分区对象：

```json
{
  "id": "materials",
  "name": "自制素材",
  "description": "提供卡牌框架、立绘底图、特效等素材下载。",
  "icon": "palette", 
  "empty_title": "暂无素材文件",
  "empty_hint": "素材库建设中，敬请期待。",
  "items": [
    // 这里放入您的 items (single 或 bundle 模版)
  ]
}
```

> 每一个 Section 的 `id` 应该唯一，`icon` 使用 Material Icons 的标志名称（如 `"palette"`, `"video_library"`, `"extension"` 等）。

---

## 四、保存与测试

1. 打开 [downloads.json](downloads.json)。
2. 在合适的分类下的 `"items"` 数组中，粘贴上面写好的模版。
3. 修改属性并保存。
4. 运行服务，打开 `/downloads` 页面或刷新，即可实时看到新添加的资源。
