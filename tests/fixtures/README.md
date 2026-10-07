# Unity 回归样本

`card_data_5` 是用户明确要求支持的原始 Bundle 的未修改副本，大小 133697 字节，SHA-256：`e0682de0135a77bcd15c73072dc3221c0e25b1ac694ebc86bd7965e1d56d57b7`。

包含一个卡牌 TextAsset 和一个 AssetBundle 对象，卡牌正文有 650 个条目。此文件只用于回归测试，不是服务端运行底包。`tests/test_card_data_5.py` 在 Linux 上通过真实受限子进程验证 HTTP 解包和回填；Windows 可运行同文件内的预算测试。
