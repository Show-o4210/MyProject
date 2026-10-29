# 启动器项目留言与名单

`GET /api/pvzh-launcher/v1/project.json`读取部署内`data/launcher-project.json`，独立于启动器版本／公告、DIY版本、玩家精选和旧赞助接口。它只提供项目介绍、仓库说明与公开名称，不接受用户留言、表单、上传或配置编辑。

```json
{
  "schema_version": 1,
  "product": "pvzh-launcher",
  "updated_at": "2026-10-30",
  "title": "致每一位有想法的玩家",
  "paragraphs": ["项目介绍纯文本"],
  "repository_note": "GitHub：PVZH-Library目前为私人仓库，正式版本发布后会一同公开。",
  "supporters": [],
  "contributors": []
}
```

## 精确合同

根对象只允许上面八个字段，缺失或增加字段均拒绝。`schema_version`必须为整数1，布尔、浮点、字符串不可替代；`product`必须为`pvzh-launcher`。`updated_at`是有效且规范的`YYYY-MM-DD`日期，不接受时间戳或紧凑日期。

| 字段 | 上限与形式 |
|---|---|
| `title` | 非空白纯文本，最多120个Unicode码点，单行 |
| `paragraphs` | 字符串数组，最多20段；每段最多2000码点，允许空字符串，可含换行、回车和Tab |
| `repository_note` | 单行纯文本，最多400码点，可空 |
| `supporters`、`contributors` | 各最多100项；每项为非空白单行字符串，最多80码点，保留次序 |

名单字段只接受名称字符串，不接受带链接、图片或身份字段的对象；看起来像HTML或地址的字符串也只能由客户端按字面纯文本显示。所有数组允许为空，空名单可以明确清空客户端旧名称。初始两份名单为空，不把旧`data/sponsors.json`中的历史名称自动视为本项目赞赏者或贡献者。

原始UTF-8文件和实际UTF-8响应各最多64KiB，字符数限制不替代总字节限制。拒绝重复JSON键、NaN／Infinity、错误类型、非法UTF-8、孤立代理项、替换字符、DEL及不允许的控制字符。不会更改应用全局JSON编码设置。

## 响应与保护

有效快照返回200、`application/json`、公开CORS和no-store。配置缺失、损坏、超限或不满足合同返回JSON503及`code=LAUNCHER_PROJECT_UNAVAILABLE`，不返回部分名单或源码默认留言。HEAD与GET状态、头部一致且无正文；OPTIONS明确列出GET／HEAD／OPTIONS，不读取快照；写入方法返回405。

新增端点继续经过现有跨路径单IP／全站限流，拒绝后不读取快照。无新的管理员令牌、数据库、编辑器或出站请求。GitHub按钮固定指向客户端内置的Library仓库地址，服务器只提供`repository_note`文字，不能远程替换按钮URL。

修改快照后运行`python scripts/validate_snapshots.py`及`python -m pytest -q`，审阅并部署后生效。上线后另检查正式HTTPS的字段、CORS／no-store、错误与客户端离线回退；本机测试不代替线上或Android实测。
