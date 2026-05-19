import json
import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, webhook_url: str, failures_path: Path, timeout: float = 10.0):
        self._url = webhook_url
        self._failures_path = Path(failures_path)
        self._http = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._http.close()

    def send(self, payload: dict) -> None:
        try:
            r = self._http.post(self._url, json=payload)
            if not (200 <= r.status_code < 300):
                self._buffer(payload, f"http {r.status_code}")
            return
        except Exception as e:
            self._buffer(payload, f"{type(e).__name__}: {e}")

    def _buffer(self, payload: dict, reason: str) -> None:
        log.warning("webhook delivery failed (%s); buffering to %s", reason, self._failures_path)
        with self._failures_path.open("a") as f:
            f.write(json.dumps(payload) + "\n")
