# 关卡与卡组工具归档 · 2026-10-21

此目录按原路径保存关卡编辑器、卡组编辑器的原始源码、页面、专用数据、底包和测试。归档文件不由 Flask static 提供，也不被应用启动导入。

旧页面 `/editor`、`/deck-editor` 和原有六个 API 由生产目录中的轻量蓝图返回 HTTP 410；首页与两处 sitemap 已撤下入口。浏览器历史数据不清除。

`utils/json_requests.py`、`utils/unity_worker.py`、原 README 和架构说明为归档前快照。生产版本仅保留 Unity 解包/回填所需逻辑。原 `tests/test_isolation.py` 为完整快照；在线测试继续验证通用 Unity 隔离。

三个 Unity 底包仍作为通用 Unity 回归样本由现行测试直接读取本目录，并不用于在线关卡或卡组功能。共享的 JSON、导出预算、锁等依赖仍在生产 `utils/`、`extensions.py`；恢复时应核对接口兼容性。

如需恢复，应先在独立分支把专用文件按原路径移回，合并共享文件快照而非直接覆盖，再恢复原测试与首页、sitemap 入口。归档测试不属于当前 CI；恢复后需在 Linux 验证完整编辑、打包流程。
