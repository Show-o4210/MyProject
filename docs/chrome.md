太棒了，那我们把这套针对你 **PVZH Mod 工具箱** 的定制化 SEO 收录方案做个最终盘点。

既然你的 Google Search Console (GSC) 已经顺利验证通过，接下来的核心目标就是：**在不破坏你聪明的“防封/省额度作息表”的前提下，让谷歌完美收录全站。**

以下是最终落地的行动清单：

---

## 🛠️ 第一部分：代码与配置落地（一次性搞定）

### 1. 动态注入 `robots.txt` 与 `sitemap.xml`

直接在你的首页蓝图（`blueprints/home.py`） 中添加这两个路由，避免手动维护静态文件。**记住不要把 `/api/` 路由放进站点地图。**

```python
from flask import Blueprint, Response

home_bp = Blueprint('home', __name__)

@home_bp.route('/robots.txt')
def robots_txt():
    content = """User-agent: *
Allow: /

Sitemap: https://pvz-h-tools.onrender.com/sitemap.xml
"""
    return Response(content, mimetype="text/plain")

@home_bp.route('/sitemap.xml')
def sitemap_xml():
    # 显式声明需要谷歌收录的页面
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://pvz-h-tools.onrender.com/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
  <url><loc>https://pvz-h-tools.onrender.com/downloads</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>
  <url><loc>https://pvz-h-tools.onrender.com/deck_editor</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
  <url><loc>https://pvz-h-tools.onrender.com/level_editor</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>
</urlset>
"""
    return Response(content, mimetype="application/xml")

```

### 2. 补全 `base.html` 的 SEO 关键词

检查 `templates/base.html`，确保 `<head>` 标签里有清晰的定位，方便谷歌在搜索结果中展示漂亮的标题和摘要：

```html
<title>{% block title %}PVZH Mod 工具箱 - Plants vs. Zombies Heroes 在线辅助工具{% endblock %}</title>
<meta name="description" content="全功能 PVZ Heroes 在线 Mod 辅助工具箱。提供卡组在线编辑、关卡底包读写、Unity AB包解包回填、幻影卡牌工坊及官方卡包模拟购买。">
<meta name="keywords" content="PVZH, 植物大战僵尸英雄, PVZ Heroes, Mod工具, 卡组编辑器, 关卡编辑器, UnityPy">

```

### 3. 确保下载中心（Downloads）可被顺藤摸瓜

你的下载条目保存在 `data/downloads.json` 中。确保在 `tab_downloads.html` 列表页上，每个 Mod 的卡片都包裹在一个标准的 `<a href="/downloads/{{ item.id }}">` 标签里。只要谷歌爬虫进入了 `/downloads`，它就会顺着这些链接自动把所有 Mod 详情页都抓取并建立索引。

---

## ⏰ 第二部分：运行策略与日常维护（完美兼顾防封与收录）

### 1. 坚持你的“作息策略”（8:00 - 24:00 唤醒，0:00 - 8:00 休眠）

* **保留该策略**：这能有效伪装成真人访问，降低被 Render 官方判定为“恶意挂机”的风险，同时为你的账户节省免费运行额度（利大于弊，保住账号是第一位的）。

### 2. 白天进行“人工干预”弥补夜间休眠

* **黄金法则**：因为你的网站在白天（8点到24点）是 100% 保持活跃的，在这个时间段内，你可以随时登录 **Google Search Console**。
* **主动出击**：在 GSC 顶部的搜索栏输入你的首页网址或新发布的 Mod 链接，点击 **“请求编入索引”**。
* **效果**：谷歌会立刻派一个临时爬虫过来，此时你的 Render 实例正处于活跃状态，爬虫可以在几秒内完成近乎完美的抓取，彻底规避夜间休眠导致的连接超时问题。

---

把代码部署上去，并在白天去 GSC 提交一下你的 `sitemap.xml`，接下来交给时间，等待谷歌把你的 PVZH 工具箱呈现在全球玩家面前吧！
