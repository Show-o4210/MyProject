"""Validate the single public cloud-drive download link."""
import json
from pathlib import Path
from urllib.parse import urlsplit

DATA_PATH = Path(__file__).resolve().parents[1] / "data/downloads.json"


def main():
    try:
        data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"url"} or not isinstance(data["url"], str):
            raise ValueError("配置必须仅包含字符串 url")
        url = urlsplit(data["url"])
        if url.scheme != "https" or url.hostname != "pan.quark.cn" or url.username or url.password or url.port not in (None, 443) or not url.path.startswith("/s/") or not url.path[3:]:
            raise ValueError("请使用有效的夸克网盘 HTTPS 分享链接")
    except (OSError, ValueError) as error:
        print(f"[ERROR] 下载链接配置无效：{error}")
        return 1
    print("通过：1 个夸克网盘入口")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
