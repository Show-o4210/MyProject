# Unity 回归样本

`card_data_5` 是用户明确要求支持的原始 Bundle 的未修改副本，大小 133697 字节，SHA-256：`e0682de0135a77bcd15c73072dc3221c0e25b1ac694ebc86bd7965e1d56d57b7`。

包含一个卡牌 TextAsset 和一个 AssetBundle 对象，卡牌正文有 650 个条目。此文件只用于回归测试，不是服务端运行底包。`tests/test_card_data_5.py` 在 Linux 上通过真实受限子进程验证 HTTP 解包和回填；Windows 可运行同文件内的预算测试。

`card_data_1` 和 `card_data_1_modified.zip` 是 2026-10-14 用户反馈的原始 Bundle 与补丁 ZIP 未修改副本。Bundle 为 167440 字节，SHA-256：`6dbfaff6778e83b6d6ecd1725bc36436c3d143ee15c31703ee239fe094d3898c`；补丁为 314244 字节，内含一份约 12 MiB 的卡片 typetree JSON，包含尾逗号、负数 path_id 和外层目录。

卡片正文有 660 个条目，补丁修改其中 59 张卡牌。`tests/test_card_data_1.py` 在 Linux 上通过真实受限子进程回填并重新加载校验；另在原 Bundle 的正文副本中加入尾逗号，覆盖 JSON/CSV × auto/manual 的导出、真实攻击数值 4→5 修改、回填与其他对象完整性。Windows 可运行该文件内的解析预算测试。
