# 部署与运维

## Render

仓库的 `render.yaml` 使用 Python 3.12.3，构建命令为：

```text
pip install -r requirements.txt && python scripts/generate_sitemap.py
```

启动命令为：

```text
gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120 --max-requests 500 --max-requests-jitter 50 --access-logfile - --error-logfile -
```

如果 Render Dashboard 中配置了自定义 Build Command 或 Start Command，应与仓库配置保持一致。

## 环境变量

以 `.env.example` 为基准在部署平台配置变量，不要上传真实 `.env`。

- 反馈和安全日志需要 `SUPABASE_URL` 与 `SUPABASE_KEY`。
- 自定义域名应设置 `SITE_BASE_URL`，避免 sitemap 继续输出默认域名。
- 如启用进程内自唤醒，`SELF_PING_URL` 必须指向本站 `/health`；可同时设置 `SELF_PING_TOKEN`。
- EA/PopCap 相关默认参数可通过 `PVZH_*` 覆盖。

## Supabase

按功能执行：

- `sql/feedbacks.sql`：创建反馈表、RLS 和 INSERT-only 权限。
- `sql/security_logs.sql`：创建安全审计表及写入权限。

后端使用 anon key 时，插入操作不能依赖插入后的 SELECT 回读。当前反馈服务已按 `returning=minimal` 约定处理。

## SEO

- 根路径 `/robots.txt` 与 `/sitemap.xml` 由 `blueprints/home.py` 提供。
- `scripts/generate_sitemap.py` 在构建时同步生成静态版本。
- 新增可公开索引的固定页面时，需要同步检查 `_STATIC_SITEMAP_PAGES` 和生成脚本。
- 新增下载条目后运行 `python scripts/generate_sitemap.py`，并确认详情页 URL 出现在 sitemap 中。

## 上线检查

```powershell
python -m compileall -q .
python scripts/validate_downloads.py
python scripts/generate_sitemap.py
```

部署后至少检查：

- `/health` 返回 200。
- `/robots.txt` 和 `/sitemap.xml` 使用正确公网域名。
- 首页、下载中心和主要编辑器页面可以打开。
- 下载跳转与 GitHub 镜像列表正常。
- 配置 Supabase 后，反馈提交和安全日志写入正常。

