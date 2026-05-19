import time
import logging
from typing import Optional

import httpx

log = logging.getLogger(__name__)

BASE_URL = "https://discord.com/api/v9"
MAX_RETRIES = 5
BACKOFF_CAP = 30


class DiscordAuthError(Exception):
    """Raised when Discord returns 401 — token is invalid or expired."""


class DiscordClient:
    def __init__(self, token: str, timeout: float = 15.0):
        self._token = token
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": token},
            timeout=timeout,
        )

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            r = self._http.request(method, path, **kwargs)
            if r.status_code == 401:
                raise DiscordAuthError("Discord rejected the token (401).")
            if r.status_code == 429:
                retry_after = float(r.json().get("retry_after", 1))
                log.warning("rate-limited; sleeping %.2fs", retry_after)
                time.sleep(retry_after)
                continue
            if 500 <= r.status_code < 600:
                if attempt >= MAX_RETRIES:
                    r.raise_for_status()
                sleep_for = min(2 ** attempt, BACKOFF_CAP)
                log.warning("server error %d; backing off %ds", r.status_code, sleep_for)
                time.sleep(sleep_for)
                attempt += 1
                continue
            r.raise_for_status()
            return r

    def get_current_user(self) -> dict:
        return self._request("GET", "/users/@me").json()

    def get_messages(self, channel_id: str, limit: int = 50, after: Optional[str] = None) -> list[dict]:
        params: dict[str, str | int] = {"limit": limit}
        if after:
            params["after"] = after
        return self._request("GET", f"/channels/{channel_id}/messages", params=params).json()

    def get_message(self, channel_id: str, message_id: str) -> Optional[dict]:
        r = self._http.get(f"/channels/{channel_id}/messages/{message_id}")
        if r.status_code == 404:
            return None
        if r.status_code == 401:
            raise DiscordAuthError("Discord rejected the token (401).")
        r.raise_for_status()
        return r.json()

    def send_message(self, channel_id: str, content: str) -> dict:
        return self._request(
            "POST",
            f"/channels/{channel_id}/messages",
            json={"content": content},
        ).json()

    def list_guilds(self) -> list[dict]:
        return self._request("GET", "/users/@me/guilds").json()

    def list_guild_channels(self, guild_id: str) -> list[dict]:
        return self._request("GET", f"/guilds/{guild_id}/channels").json()

    def list_dms(self) -> list[dict]:
        return self._request("GET", "/users/@me/channels").json()
