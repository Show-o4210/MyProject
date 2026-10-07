# 幻影引擎归档 · 2026-10-07

此目录保存归档时的完整工具源码和专用资源，目录布局沿用原项目路径。在线首页、导航和 sitemap 已撤下入口；`/phantom` 返回归档说明及 HTTP 410，原 ping/config API 同样返回 410。

保留内容：原 `blueprints/phantom.py` 与 `logic_phantom_config.py`、原页面模板、CSS、全部 Phantom JavaScript、静态配置。共用的 `json_budget.js` / `json_worker.js` 留在生产目录，并在此保存快照，使归档模块及其原有前端回归测试可读取依赖。

归档不清除客户端 localStorage，原键 `pvzh_phantom_single_card_v1` 及旧草稿迁移逻辑保留在源码中。恢复前应核对 `static/js/phantom/state.js` 中的键名及共享依赖版本。

如需恢复，将专用文件按对应路径移回主项目（覆盖退役蓝图、恢复原模板；共用 JSON 文件不必覆盖），再恢复首页、导航与两处 sitemap 入口。归档目录不位于 Flask static 根目录，不作为在线资源提供。
