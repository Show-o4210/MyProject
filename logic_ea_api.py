import os
import re
import time
from typing import Any

import requests

EA_SOFT_PURCHASE_URL = (
    "https://pvz-heroes.awspopcap.com/persistence/v2/inventory/commitSoftPurchase"
)
EA_DAILY_LOGIN_URL = (
    "https://pvz-heroes.awspopcap.com/updateDailyLoginProgress"
)
EA_LEAGUE_SYNC_URL = (
    "https://pvz-heroes.awspopcap.com/pvp/v1/leagueRewards/sync"
)
EA_PLAYER_INFO_URL = (
    "https://pvz-heroes.awspopcap.com/player/v1/playerInfo"
)
EA_AUTH_URL = "https://eadp.ea.com/accounts/api/v1/anonymous/login"

CLIENT_ID = os.getenv("PVZH_CLIENT_ID", "pvzheroes-2015-google-client")
EA_REFRESH_CLIENT_ID = os.getenv("EA_REFRESH_CLIENT_ID", "ea-pvzheroes-production")
EA_REFRESH_CLIENT_SECRET = os.getenv(
    "EA_REFRESH_CLIENT_SECRET", "78a158d0-9f4b-4c8a-901e-2b3c4d5e6f7a"
)
DEFAULT_CLIENT_VERSION = os.getenv("PVZH_CLIENT_VERSION", "1.64.6")
DEFAULT_CONTENT_VERSION = os.getenv(
    "PVZH_CONTENT_VERSION", "45a337051e72592e53c9bf8a4b590639"
)
DEFAULT_PLATFORM = os.getenv("PVZH_PLATFORM", "Android")
DEFAULT_REQUEST_TIMEOUT = int(os.getenv("PVZH_REQUEST_TIMEOUT", "12"))
TOKEN_EXPIRY_BUFFER_SECONDS = 300
STORED_TOKEN_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "token.dat"
)


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


def extract_printable_text(content: bytes) -> str:
    return "".join(chr(c) for c in content if 32 <= c <= 126)


def parse_credentials_from_dat(content: bytes) -> dict[str, Any]:
    """从 nimble .dat 二进制凭证文件中提取 access/refresh token。"""
    text = extract_printable_text(content)
    credentials: dict[str, Any] = {}

    match = re.search(r'"access_token":"([^"]+)"', text)
    if match:
        credentials["access_token"] = match.group(1)

    match = re.search(r'"refresh_token":"([^"]+)"', text)
    if match:
        credentials["refresh_token"] = match.group(1)

    match = re.search(r'"accessTokenExpiresAt":(\d+)', text)
    if match:
        credentials["expires_at"] = int(match.group(1))

    return credentials


def check_token_valid(expires_at: int | None) -> bool:
    if not expires_at:
        return False
    return int(time.time()) < (int(expires_at) - TOKEN_EXPIRY_BUFFER_SECONDS)


def refresh_access_token(refresh_token: str) -> dict[str, Any] | None:
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Expand-Results": "true",
        "X-Include-Underage": "true",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": EA_REFRESH_CLIENT_ID,
        "client_secret": EA_REFRESH_CLIENT_SECRET,
        "redirect_uri": "nucleus:rest",
    }

    try:
        response = requests.post(
            EA_AUTH_URL,
            headers=headers,
            data=data,
            timeout=DEFAULT_REQUEST_TIMEOUT,
        )
        if response.status_code != 200:
            return None

        result = response.json()
        access_token = result.get("access_token")
        if not access_token:
            return None

        expires_in = int(result.get("expires_in", 3600))
        return {
            "access_token": access_token,
            "refresh_token": result.get("refresh_token") or refresh_token,
            "expires_at": int(time.time()) + expires_in,
        }
    except requests.RequestException:
        return None


def ensure_valid_token(
    token: str,
    refresh_token: str | None,
    expires_at: int | None,
) -> tuple[str, str | None, int | None, bool]:
    """必要时刷新 Token，返回 (token, refresh_token, expires_at, refreshed)。"""
    if check_token_valid(expires_at):
        return token, refresh_token, expires_at, False

    if not refresh_token:
        return token, refresh_token, expires_at, False

    new_creds = refresh_access_token(refresh_token)
    if not new_creds:
        return token, refresh_token, expires_at, False

    return (
        new_creds["access_token"],
        new_creds["refresh_token"],
        new_creds["expires_at"],
        True,
    )


def load_stored_credentials() -> dict[str, Any]:
    """从 data/token.dat 读取长期凭证。"""
    if not os.path.exists(STORED_TOKEN_FILE):
        return {"success": False, "error": f"凭证文件不存在: data/token.dat"}

    try:
        with open(STORED_TOKEN_FILE, "rb") as f:
            content = f.read()
    except OSError as exc:
        return {"success": False, "error": f"读取凭证文件失败: {exc}"}

    credentials = parse_credentials_from_dat(content)
    if not credentials.get("access_token"):
        return {
            "success": False,
            "error": "data/token.dat 中未找到 access_token，请检查文件内容。",
        }

    credentials["success"] = True
    credentials["source"] = "data/token.dat"
    return credentials


def resolve_request_credentials(data: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """解析前端提交的认证字段，支持本地凭证与自动续期。"""
    auth_mode = str(data.get("auth_mode", "manual")).strip().lower()
    token = str(data.get("token", "")).strip()
    persona_id = str(data.get("persona_id", "")).strip()
    refresh_token = str(data.get("refresh_token", "")).strip() or None
    auto_refresh = bool(data.get("auto_refresh", False))

    expires_at: int | None = None
    raw_expires = data.get("expires_at")
    if raw_expires not in (None, ""):
        try:
            expires_at = int(raw_expires)
        except (TypeError, ValueError):
            expires_at = None

    meta: dict[str, Any] = {
        "auth_mode": auth_mode,
        "auto_refresh": auto_refresh,
    }

    if auth_mode == "auto":
        stored = load_stored_credentials()
        meta["stored_credentials_loaded"] = stored.get("success", False)
        if stored.get("success"):
            token = stored.get("access_token", token)
            if not refresh_token:
                refresh_token = stored.get("refresh_token")
            if expires_at is None:
                expires_at = stored.get("expires_at")
            auto_refresh = True
            meta["credential_source"] = stored.get("source", "data/token.dat")
        else:
            meta["stored_credentials_error"] = stored.get("error")

    meta["token_valid_before"] = check_token_valid(expires_at)
    meta["auto_refresh"] = auto_refresh

    if auto_refresh and refresh_token:
        token, refresh_token, expires_at, refreshed = ensure_valid_token(
            token, refresh_token, expires_at
        )
        meta["token_refreshed"] = refreshed
        if refreshed:
            meta["access_token"] = token
            meta["refresh_token"] = refresh_token
            meta["expires_at"] = expires_at

    meta["token_valid_after"] = check_token_valid(expires_at)
    return token, persona_id, meta


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


def post_daily_login(
    persona_id: str,
    headers: dict[str, str],
    timeout: int | None = None,
) -> requests.Response:
    url = f"{EA_DAILY_LOGIN_URL}?userId={persona_id}"
    body = {
        "day": 1,
        "forStreak": True,
        "currentStreakSetCompleted": False,
    }
    return requests.post(
        url,
        json=body,
        headers=headers,
        timeout=timeout or DEFAULT_REQUEST_TIMEOUT,
    )


def post_league_sync(
    persona_id: str,
    headers: dict[str, str],
    *,
    gems: int = 10000,
    timeout: int | None = None,
) -> requests.Response:
    url = f"{EA_LEAGUE_SYNC_URL}?playerId={persona_id}"
    body = {
        "tickets": 0,
        "gems": gems,
        "sparks": 0,
        "packs": [],
        "specificCards": [],
    }
    return requests.post(
        url,
        json=body,
        headers=headers,
        timeout=timeout or DEFAULT_REQUEST_TIMEOUT,
    )


def get_player_info(
    persona_id: str,
    headers: dict[str, str],
    timeout: int | None = None,
) -> requests.Response:
    url = f"{EA_PLAYER_INFO_URL}?userId={persona_id}"
    return requests.get(
        url,
        headers=headers,
        timeout=timeout or DEFAULT_REQUEST_TIMEOUT,
    )