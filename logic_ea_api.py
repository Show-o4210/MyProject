import os
import time
from typing import Any

import requests

EA_SOFT_PURCHASE_URL = (
    "https://pvz-heroes.awspopcap.com/persistence/v2/inventory/commitSoftPurchase"
)

CLIENT_ID = os.getenv("PVZH_CLIENT_ID", "pvzheroes-2015-google-client")
DEFAULT_CLIENT_VERSION = os.getenv("PVZH_CLIENT_VERSION", "1.64.6")
DEFAULT_CONTENT_VERSION = os.getenv(
    "PVZH_CONTENT_VERSION", "45a337051e72592e53c9bf8a4b590639"
)
DEFAULT_PLATFORM = os.getenv("PVZH_PLATFORM", "Android")
DEFAULT_REQUEST_TIMEOUT = int(os.getenv("PVZH_REQUEST_TIMEOUT", "12"))


def utc_timestamp_ms() -> str:
    return str(int(time.time() * 1000))


def build_pvzh_headers(
    token: str,
    persona_id: str,
    *,
    client_version: str | None = None,
    content_version: str | None = None,
    platform: str | None = None,
) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "EADP-AUTH-TOKEN": token,
        "EADP-PERSONA-ID": persona_id,
        "X-EADP-Client-Id": CLIENT_ID,
        "X-Pvzh-UTC": utc_timestamp_ms(),
        "X-Pvzh-Platform": platform or DEFAULT_PLATFORM,
        "X-Pvzh-Content-Version": content_version or DEFAULT_CONTENT_VERSION,
        "X-Pvzh-Client-Version": client_version or DEFAULT_CLIENT_VERSION,
    }


def post_soft_purchase(
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: int | None = None,
) -> requests.Response:
    return requests.post(
        EA_SOFT_PURCHASE_URL,
        json=payload,
        headers=headers,
        timeout=timeout or DEFAULT_REQUEST_TIMEOUT,
    )