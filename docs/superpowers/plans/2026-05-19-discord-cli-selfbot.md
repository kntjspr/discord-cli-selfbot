# Discord CLI Selfbot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI (`dcli`) that signs in as a Discord user account, watches channels via REST polling, downloads image attachments, and POSTs every create/edit/delete event to a local webhook for openclaw / claude code to consume.

**Architecture:** Direct Discord API v9 calls over `httpx`. Click CLI with five subcommands. Listen loop maintains a per-channel rolling window of recent message IDs in `.dcli-state.json`, diffs each poll cycle to detect creates/edits/deletes, downloads attachments to `./attachments/{msg_id}/`, posts to webhook. Failed webhook deliveries are buffered to a JSONL file.

**Tech Stack:** Python 3.10+, `httpx`, `click`, `python-dotenv`, `pytest` + `pytest-httpx`. No discord.py.

**Spec:** `docs/superpowers/specs/2026-05-19-discord-cli-selfbot-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, deps, `dcli` console_script entry point |
| `.env.example` | Documented env vars (DISCORD_TOKEN, WEBHOOK_URL) |
| `.gitignore` | Hide `.env`, `attachments/`, state files, build artifacts |
| `dcli/__init__.py` | Package marker, version constant |
| `dcli/__main__.py` | `python -m dcli` → `cli.main()` |
| `dcli/client.py` | `DiscordClient` — REST wrapper, retries, 429/5xx handling |
| `dcli/state.py` | Load/save `.dcli-state.json` atomically; per-channel window |
| `dcli/attachments.py` | Download attachments, sanitize filenames, idempotent |
| `dcli/notifier.py` | POST to webhook; on failure append to `.dcli-failed-deliveries.jsonl` |
| `dcli/listener.py` | Poll loop, diff algorithm (create/update/delete), graceful shutdown |
| `dcli/cli.py` | Click commands: `listen`, `fetch`, `send`, `channels`, `dms` |
| `tests/test_client.py` | Mock httpx; assert URL/headers/body for each method |
| `tests/test_state.py` | Round-trip save/load; corruption recovery |
| `tests/test_attachments.py` | Mock download; filename sanitization; idempotency |
| `tests/test_notifier.py` | Mock webhook; payload shape; failed-delivery buffering |
| `tests/test_listener_diff.py` | Synthetic message lists → assert correct events emitted |
| `README.md` | Quickstart |

---

## Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`
- Create: `dcli/__init__.py`, `dcli/__main__.py`, `tests/__init__.py`
- Delete: `discord_test.py` (superseded; commit removal separately so history is clean)

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "dcli"
version = "0.1.0"
description = "Discord user-account CLI: listen, fetch, send, with webhook notifications."
requires-python = ">=3.10"
dependencies = [
  "httpx>=0.27",
  "click>=8.1",
  "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-httpx>=0.30",
]

[project.scripts]
dcli = "dcli.cli:main"

[tool.setuptools.packages.find]
include = ["dcli*"]
exclude = ["tests*"]
```

- [ ] **Step 2: Create `.gitignore`**

```
.env
.venv/
__pycache__/
*.egg-info/
build/
dist/
.dcli-state.json
.dcli-state.json.tmp
.dcli-failed-deliveries.jsonl
attachments/
.pytest_cache/
```

- [ ] **Step 3: Create `.env.example`**

```
DISCORD_TOKEN=your_user_token_here
WEBHOOK_URL=http://localhost:8787/discord
```

- [ ] **Step 4: Create `dcli/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 5: Create `dcli/__main__.py`**

```python
from dcli.cli import main

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Create `tests/__init__.py`** (empty file)

- [ ] **Step 7: Create `README.md`**

```markdown
# dcli — Discord CLI Selfbot

A small Python CLI that signs into a Discord user account, watches channels, and forwards every new/edited/deleted message (plus downloaded image attachments) to a local HTTP webhook.

**Warning:** Discord's ToS prohibits self-bots. Use at your own risk.

## Install

    pip install -e ".[dev]"
    cp .env.example .env  # then fill in DISCORD_TOKEN and WEBHOOK_URL

## Commands

    dcli listen <channel_id> [<channel_id> ...]
    dcli fetch <channel_id> [--limit 50] [--json]
    dcli send <channel_id> <message>
    dcli channels [--guild GUILD_ID]
    dcli dms

See `docs/superpowers/specs/2026-05-19-discord-cli-selfbot-design.md` for the full design.
```

- [ ] **Step 8: Install and verify**

Run: `cd /home/xo/temp/discord-cli-selfbot && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: installs without error.

Run: `python -c "import dcli; print(dcli.__version__)"`
Expected: `0.1.0`

- [ ] **Step 9: Remove old test script**

Run: `git rm discord_test.py 2>/dev/null || rm -f discord_test.py`

- [ ] **Step 10: Commit**

```bash
git init 2>/dev/null  # if not already a repo
git add pyproject.toml .gitignore .env.example README.md dcli/ tests/__init__.py
git rm --cached discord_test.py 2>/dev/null || true
git commit -m "feat: scaffold dcli package with pyproject and entry point"
```

---

## Task 2: DiscordClient — REST wrapper (TDD)

**Files:**
- Create: `tests/test_client.py`
- Create: `dcli/client.py`

The client owns all HTTP. It handles auth header, 401 (fatal), 429 (sleep `retry_after`), 5xx (exponential backoff: 1s, 2s, 4s, 8s, capped 30s, max 5 retries). It exposes typed methods, not a generic `request()`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_client.py`:

```python
import pytest
from pytest_httpx import HTTPXMock

from dcli.client import DiscordClient, DiscordAuthError


BASE = "https://discord.com/api/v9"


def test_get_messages_builds_correct_request(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/channels/123/messages?limit=50",
        json=[{"id": "1", "content": "hi"}],
    )
    client = DiscordClient(token="tok")
    msgs = client.get_messages("123", limit=50)
    assert msgs == [{"id": "1", "content": "hi"}]
    req = httpx_mock.get_request()
    assert req.headers["Authorization"] == "tok"


def test_get_message_returns_none_on_404(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/channels/123/messages/999",
        status_code=404,
        json={"message": "Unknown Message", "code": 10008},
    )
    client = DiscordClient(token="tok")
    assert client.get_message("123", "999") is None


def test_get_message_returns_payload_on_200(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/channels/123/messages/999",
        json={"id": "999", "content": "still here"},
    )
    client = DiscordClient(token="tok")
    assert client.get_message("123", "999") == {"id": "999", "content": "still here"}


def test_send_message_posts_content(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/channels/123/messages",
        method="POST",
        json={"id": "new", "content": "hello"},
    )
    client = DiscordClient(token="tok")
    out = client.send_message("123", "hello")
    assert out["id"] == "new"
    req = httpx_mock.get_request()
    assert req.read() == b'{"content": "hello"}'


def test_list_guilds(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/users/@me/guilds",
        json=[{"id": "g1", "name": "Server"}],
    )
    client = DiscordClient(token="tok")
    assert client.list_guilds() == [{"id": "g1", "name": "Server"}]


def test_list_guild_channels(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/guilds/g1/channels",
        json=[{"id": "c1", "name": "general", "type": 0}],
    )
    client = DiscordClient(token="tok")
    assert client.list_guild_channels("g1")[0]["id"] == "c1"


def test_list_dms(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/users/@me/channels",
        json=[{"id": "d1", "recipients": [{"username": "alice"}]}],
    )
    client = DiscordClient(token="tok")
    assert client.list_dms()[0]["id"] == "d1"


def test_get_current_user(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/users/@me",
        json={"id": "me", "username": "self"},
    )
    client = DiscordClient(token="tok")
    assert client.get_current_user()["username"] == "self"


def test_401_raises_auth_error(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url=f"{BASE}/users/@me",
        status_code=401,
        json={"message": "401: Unauthorized", "code": 0},
    )
    client = DiscordClient(token="bad")
    with pytest.raises(DiscordAuthError):
        client.get_current_user()


def test_429_sleeps_and_retries(httpx_mock: HTTPXMock, monkeypatch):
    sleeps = []
    monkeypatch.setattr("dcli.client.time.sleep", lambda s: sleeps.append(s))
    httpx_mock.add_response(
        url=f"{BASE}/users/@me",
        status_code=429,
        json={"retry_after": 0.42},
    )
    httpx_mock.add_response(
        url=f"{BASE}/users/@me",
        json={"id": "me"},
    )
    client = DiscordClient(token="tok")
    assert client.get_current_user()["id"] == "me"
    assert sleeps == [0.42]


def test_5xx_backs_off_then_succeeds(httpx_mock: HTTPXMock, monkeypatch):
    sleeps = []
    monkeypatch.setattr("dcli.client.time.sleep", lambda s: sleeps.append(s))
    httpx_mock.add_response(url=f"{BASE}/users/@me", status_code=502)
    httpx_mock.add_response(url=f"{BASE}/users/@me", status_code=503)
    httpx_mock.add_response(url=f"{BASE}/users/@me", json={"id": "me"})
    client = DiscordClient(token="tok")
    assert client.get_current_user()["id"] == "me"
    assert sleeps == [1, 2]


def test_5xx_gives_up_after_max_retries(httpx_mock: HTTPXMock, monkeypatch):
    monkeypatch.setattr("dcli.client.time.sleep", lambda s: None)
    for _ in range(6):
        httpx_mock.add_response(url=f"{BASE}/users/@me", status_code=502)
    client = DiscordClient(token="tok")
    with pytest.raises(Exception):
        client.get_current_user()
```

- [ ] **Step 2: Run tests, confirm all fail**

Run: `pytest tests/test_client.py -v`
Expected: `ModuleNotFoundError: No module named 'dcli.client'` or similar.

- [ ] **Step 3: Implement `dcli/client.py`**

```python
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
```

- [ ] **Step 4: Run tests, confirm all pass**

Run: `pytest tests/test_client.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add dcli/client.py tests/test_client.py
git commit -m "feat: add DiscordClient REST wrapper with 401/429/5xx handling"
```

---

## Task 3: State persistence (TDD)

**Files:**
- Create: `tests/test_state.py`
- Create: `dcli/state.py`

State tracks a rolling window of recent message IDs per channel for the diff algorithm. Atomic writes via tmp-file-rename. Corrupt state is logged and treated as first run.

- [ ] **Step 1: Write failing tests**

Create `tests/test_state.py`:

```python
import json
from pathlib import Path

from dcli.state import State, WindowEntry


def test_first_load_returns_empty(tmp_path: Path):
    s = State.load(tmp_path / "state.json")
    assert s.get_channel("123") is None


def test_save_and_reload_round_trip(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State.load(p)
    s.set_channel("123", [WindowEntry(id="1", edited_timestamp=None, content_hash="abc")])
    s.save()

    s2 = State.load(p)
    win = s2.get_channel("123")
    assert win is not None
    assert win[0].id == "1"
    assert win[0].content_hash == "abc"


def test_atomic_write_uses_tmp_file(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State.load(p)
    s.set_channel("123", [WindowEntry(id="1", edited_timestamp=None, content_hash="a")])
    s.save()
    assert p.exists()
    assert not (tmp_path / "state.json.tmp").exists()


def test_corrupt_state_treated_as_empty(tmp_path: Path):
    p = tmp_path / "state.json"
    p.write_text("not json {{{")
    s = State.load(p)
    assert s.get_channel("123") is None


def test_multiple_channels_independent(tmp_path: Path):
    p = tmp_path / "state.json"
    s = State.load(p)
    s.set_channel("a", [WindowEntry(id="1", edited_timestamp=None, content_hash="h1")])
    s.set_channel("b", [WindowEntry(id="2", edited_timestamp="t", content_hash="h2")])
    s.save()
    s2 = State.load(p)
    assert s2.get_channel("a")[0].id == "1"
    assert s2.get_channel("b")[0].edited_timestamp == "t"
```

- [ ] **Step 2: Run tests, confirm failures**

Run: `pytest tests/test_state.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `dcli/state.py`**

```python
import json
import logging
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class WindowEntry:
    id: str
    edited_timestamp: Optional[str]
    content_hash: str


class State:
    def __init__(self, path: Path, data: dict):
        self._path = path
        self._data = data  # {"channels": {channel_id: [WindowEntry-dicts]}}

    @classmethod
    def load(cls, path: Path) -> "State":
        path = Path(path)
        if not path.exists():
            return cls(path, {"channels": {}})
        try:
            raw = json.loads(path.read_text())
            if not isinstance(raw, dict) or "channels" not in raw:
                raise ValueError("missing channels key")
            return cls(path, raw)
        except (json.JSONDecodeError, ValueError) as e:
            log.warning("state file %s is corrupt (%s); treating as empty", path, e)
            return cls(path, {"channels": {}})

    def get_channel(self, channel_id: str) -> Optional[list[WindowEntry]]:
        raw = self._data["channels"].get(channel_id)
        if raw is None:
            return None
        return [WindowEntry(**entry) for entry in raw]

    def set_channel(self, channel_id: str, window: list[WindowEntry]) -> None:
        self._data["channels"][channel_id] = [asdict(e) for e in window]

    def save(self) -> None:
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        os.replace(tmp, self._path)
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_state.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add dcli/state.py tests/test_state.py
git commit -m "feat: add atomic State persistence for per-channel windows"
```

---

## Task 4: Attachment downloader (TDD)

**Files:**
- Create: `tests/test_attachments.py`
- Create: `dcli/attachments.py`

Downloads each attachment to `./attachments/{msg_id}/{filename}`. Sanitizes filenames (no path separators, no empty). Skips re-download if the file already exists with matching size (idempotent). On failure, returns `None` for `local_path` and a `download_error` string.

- [ ] **Step 1: Write failing tests**

Create `tests/test_attachments.py`:

```python
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from dcli.attachments import download_attachments


def test_download_single_attachment(tmp_path: Path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://cdn.example/img.png", content=b"PNGDATA")
    results = download_attachments(
        message_id="42",
        attachments=[
            {"filename": "img.png", "url": "https://cdn.example/img.png", "content_type": "image/png", "size": 7}
        ],
        base_dir=tmp_path,
    )
    assert len(results) == 1
    r = results[0]
    assert r["filename"] == "img.png"
    assert r["local_path"] == str((tmp_path / "42" / "img.png").resolve())
    assert (tmp_path / "42" / "img.png").read_bytes() == b"PNGDATA"
    assert r["url"] == "https://cdn.example/img.png"
    assert r["content_type"] == "image/png"
    assert r["size"] == 7


def test_sanitize_filename_strips_path_separators(tmp_path: Path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://cdn.example/x", content=b"x")
    results = download_attachments(
        message_id="42",
        attachments=[{"filename": "../../etc/passwd", "url": "https://cdn.example/x", "content_type": "x", "size": 1}],
        base_dir=tmp_path,
    )
    saved = Path(results[0]["local_path"])
    # File must be inside attachments/42/, never escape it
    assert saved.parent == (tmp_path / "42").resolve()
    assert "/" not in saved.name and "\\" not in saved.name


def test_empty_filename_gets_fallback(tmp_path: Path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://cdn.example/x", content=b"x")
    results = download_attachments(
        message_id="42",
        attachments=[{"filename": "", "url": "https://cdn.example/x", "content_type": "x", "size": 1}],
        base_dir=tmp_path,
    )
    saved = Path(results[0]["local_path"])
    assert saved.name == "attachment_0"


def test_idempotent_skips_when_size_matches(tmp_path: Path, httpx_mock: HTTPXMock):
    target = tmp_path / "42" / "img.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"PNGDATA")
    # No mock added — if it tries to download, httpx_mock will fail
    results = download_attachments(
        message_id="42",
        attachments=[{"filename": "img.png", "url": "https://cdn.example/img.png", "content_type": "image/png", "size": 7}],
        base_dir=tmp_path,
    )
    assert results[0]["local_path"] == str(target.resolve())


def test_download_failure_records_error(tmp_path: Path, httpx_mock: HTTPXMock):
    httpx_mock.add_response(url="https://cdn.example/x", status_code=500)
    results = download_attachments(
        message_id="42",
        attachments=[{"filename": "x.png", "url": "https://cdn.example/x", "content_type": "image/png", "size": 1}],
        base_dir=tmp_path,
    )
    assert results[0]["local_path"] is None
    assert "500" in results[0]["download_error"]
```

- [ ] **Step 2: Run tests, confirm failures**

Run: `pytest tests/test_attachments.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `dcli/attachments.py`**

```python
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

_BAD_FILENAME_CHARS = re.compile(r"[/\\\x00]")


def _sanitize(name: str, fallback: str) -> str:
    cleaned = _BAD_FILENAME_CHARS.sub("_", name).strip(".").strip()
    if not cleaned or cleaned in (".", ".."):
        return fallback
    return cleaned


def download_attachments(
    message_id: str,
    attachments: list[dict],
    base_dir: Path,
    client: httpx.Client | None = None,
) -> list[dict]:
    """Returns a list of payload-ready attachment dicts."""
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=30.0)

    out: list[dict] = []
    target_dir = (Path(base_dir) / message_id).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    try:
        for i, att in enumerate(attachments):
            filename = _sanitize(att.get("filename", ""), f"attachment_{i}")
            target = target_dir / filename
            url = att["url"]
            size = att.get("size")
            content_type = att.get("content_type")

            local_path: str | None = None
            error: str | None = None

            if target.exists() and size is not None and target.stat().st_size == size:
                local_path = str(target.resolve())
            else:
                try:
                    r = client.get(url)
                    r.raise_for_status()
                    target.write_bytes(r.content)
                    local_path = str(target.resolve())
                except httpx.HTTPError as e:
                    error = f"{type(e).__name__}: {e}"
                    log.warning("attachment download failed for %s: %s", url, error)

            entry = {
                "filename": filename,
                "url": url,
                "local_path": local_path,
                "content_type": content_type,
                "size": size,
            }
            if error:
                entry["download_error"] = error
            out.append(entry)
    finally:
        if owns_client:
            client.close()

    return out
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_attachments.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add dcli/attachments.py tests/test_attachments.py
git commit -m "feat: add attachment downloader with sanitization and idempotency"
```

---

## Task 5: Webhook notifier (TDD)

**Files:**
- Create: `tests/test_notifier.py`
- Create: `dcli/notifier.py`

POSTs JSON payloads to a webhook URL. On non-2xx or network failure: log + append the payload as one JSONL line to a failures file. Never crashes the listener.

- [ ] **Step 1: Write failing tests**

Create `tests/test_notifier.py`:

```python
import json
from pathlib import Path

from pytest_httpx import HTTPXMock

from dcli.notifier import Notifier


def test_post_success(httpx_mock: HTTPXMock, tmp_path: Path):
    httpx_mock.add_response(url="http://hook/x", method="POST", status_code=200)
    n = Notifier(webhook_url="http://hook/x", failures_path=tmp_path / "fail.jsonl")
    payload = {"event": "message.create", "channel_id": "1"}
    n.send(payload)
    assert not (tmp_path / "fail.jsonl").exists()
    req = httpx_mock.get_request()
    assert json.loads(req.read()) == payload


def test_post_non_2xx_writes_failure(httpx_mock: HTTPXMock, tmp_path: Path):
    httpx_mock.add_response(url="http://hook/x", method="POST", status_code=500)
    fail = tmp_path / "fail.jsonl"
    n = Notifier(webhook_url="http://hook/x", failures_path=fail)
    n.send({"event": "x"})
    line = fail.read_text().strip()
    assert json.loads(line) == {"event": "x"}


def test_post_network_error_writes_failure(httpx_mock: HTTPXMock, tmp_path: Path):
    httpx_mock.add_exception(Exception("conn refused"), url="http://hook/x", method="POST")
    fail = tmp_path / "fail.jsonl"
    n = Notifier(webhook_url="http://hook/x", failures_path=fail)
    n.send({"event": "y"})
    line = fail.read_text().strip()
    assert json.loads(line) == {"event": "y"}


def test_multiple_failures_append(httpx_mock: HTTPXMock, tmp_path: Path):
    httpx_mock.add_response(url="http://hook/x", method="POST", status_code=500)
    httpx_mock.add_response(url="http://hook/x", method="POST", status_code=502)
    fail = tmp_path / "fail.jsonl"
    n = Notifier(webhook_url="http://hook/x", failures_path=fail)
    n.send({"event": "a"})
    n.send({"event": "b"})
    lines = fail.read_text().strip().splitlines()
    assert [json.loads(l)["event"] for l in lines] == ["a", "b"]
```

- [ ] **Step 2: Run tests, confirm failures**

Run: `pytest tests/test_notifier.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `dcli/notifier.py`**

```python
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
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_notifier.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add dcli/notifier.py tests/test_notifier.py
git commit -m "feat: add Notifier with failed-delivery buffer"
```

---

## Task 6: Listener diff algorithm (TDD)

**Files:**
- Create: `tests/test_listener_diff.py`
- Create: `dcli/listener.py`

The diff function is the highest-risk logic. We isolate it as a pure function `diff_window(prev_window, current_messages, verify_deleted) -> list[Event]` so we can hammer it with synthetic inputs. The poll loop wraps this.

`verify_deleted(message_id) -> bool` is injected; tests pass a stub.

- [ ] **Step 1: Write failing tests**

Create `tests/test_listener_diff.py`:

```python
from dcli.state import WindowEntry
from dcli.listener import diff_window, hash_content


def _msg(id: str, content: str, edited: str | None = None) -> dict:
    return {
        "id": id,
        "content": content,
        "edited_timestamp": edited,
        "author": {"id": "u", "username": "u", "global_name": None},
        "timestamp": "2026-05-19T00:00:00+00:00",
        "attachments": [],
    }


def test_first_run_emits_nothing():
    # First run is handled by listener (prev_window = None); diff_window itself
    # is only called on subsequent cycles. But we still test the empty prev case.
    events = diff_window([], [_msg("1", "hi")], window_full=False, verify_deleted=lambda _id: False)
    # No prev state → every current message is a "new" create
    assert [e["event"] for e in events] == ["message.create"]


def test_new_message_emits_create():
    prev = [WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("hi"))]
    current = [_msg("1", "hi"), _msg("2", "yo")]
    events = diff_window(prev, current, window_full=False, verify_deleted=lambda _id: False)
    assert [e["event"] for e in events] == ["message.create"]
    assert events[0]["message"]["id"] == "2"


def test_edited_message_emits_update():
    prev = [WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("hi"))]
    current = [_msg("1", "hi edited", edited="2026-05-19T01:00:00+00:00")]
    events = diff_window(prev, current, window_full=False, verify_deleted=lambda _id: False)
    assert [e["event"] for e in events] == ["message.update"]
    assert events[0]["message"]["content"] == "hi edited"


def test_gap_inside_window_is_confirmed_delete():
    prev = [
        WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a")),
        WindowEntry(id="2", edited_timestamp=None, content_hash=hash_content("b")),
        WindowEntry(id="3", edited_timestamp=None, content_hash=hash_content("c")),
    ]
    current = [_msg("1", "a"), _msg("3", "c")]
    # verify_deleted should not be called — gap is unambiguous
    called = []
    def verify(mid):
        called.append(mid)
        return True
    events = diff_window(prev, current, window_full=False, verify_deleted=verify)
    assert [e["event"] for e in events] == ["message.delete"]
    assert events[0]["message_id"] == "2"
    assert events[0]["last_known_content"] is None  # we hashed it, didn't store text
    assert called == []


def test_missing_id_past_top_is_confirmed_delete():
    # Newest message in prev no longer present → must have been deleted
    prev = [
        WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a")),
        WindowEntry(id="2", edited_timestamp=None, content_hash=hash_content("b")),
    ]
    current = [_msg("1", "a")]
    events = diff_window(prev, current, window_full=False, verify_deleted=lambda _id: True)
    assert [e["event"] for e in events] == ["message.delete"]
    assert events[0]["message_id"] == "2"


def test_missing_id_off_bottom_when_window_full_verifies():
    prev = [
        WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a")),
        WindowEntry(id="2", edited_timestamp=None, content_hash=hash_content("b")),
    ]
    # id "1" is below min(current)=2 and window is full → verify
    current = [_msg("2", "b"), _msg("3", "c")]
    verified = []
    def verify(mid):
        verified.append(mid)
        return False  # still exists, just scrolled off
    events = diff_window(prev, current, window_full=True, verify_deleted=verify)
    # 1 verified-still-alive → no delete; 3 is new → create
    assert [e["event"] for e in events] == ["message.create"]
    assert verified == ["1"]


def test_missing_id_off_bottom_when_window_full_and_verified_deleted():
    prev = [
        WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a")),
        WindowEntry(id="2", edited_timestamp=None, content_hash=hash_content("b")),
    ]
    current = [_msg("2", "b"), _msg("3", "c")]
    events = diff_window(prev, current, window_full=True, verify_deleted=lambda _id: True)
    # 1 verified deleted; 3 is new
    event_types = [e["event"] for e in events]
    assert "message.delete" in event_types and "message.create" in event_types


def test_no_changes_no_events():
    prev = [WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a"))]
    current = [_msg("1", "a")]
    events = diff_window(prev, current, window_full=False, verify_deleted=lambda _id: False)
    assert events == []


def test_creates_emitted_oldest_first():
    prev = [WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a"))]
    current = [_msg("1", "a"), _msg("2", "b"), _msg("3", "c")]
    events = diff_window(prev, current, window_full=False, verify_deleted=lambda _id: False)
    ids = [e["message"]["id"] for e in events]
    assert ids == ["2", "3"]
```

- [ ] **Step 2: Run tests, confirm failures**

Run: `pytest tests/test_listener_diff.py -v`
Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement diff in `dcli/listener.py`**

```python
import hashlib
import logging
import signal
import time
from pathlib import Path
from typing import Callable, Optional

from dcli.attachments import download_attachments
from dcli.client import DiscordClient
from dcli.notifier import Notifier
from dcli.state import State, WindowEntry

log = logging.getLogger(__name__)


def hash_content(content: str) -> str:
    return hashlib.sha1((content or "").encode("utf-8")).hexdigest()


def _build_message_payload(m: dict) -> dict:
    return {
        "id": m["id"],
        "author": {
            "id": m["author"]["id"],
            "username": m["author"]["username"],
            "global_name": m["author"].get("global_name"),
        },
        "content": m.get("content", ""),
        "timestamp": m.get("timestamp"),
        "edited_timestamp": m.get("edited_timestamp"),
        "referenced_message_id": (m.get("referenced_message") or {}).get("id"),
    }


def diff_window(
    prev_window: list[WindowEntry],
    current_messages: list[dict],
    window_full: bool,
    verify_deleted: Callable[[str], bool],
) -> list[dict]:
    """Pure diff. Returns event dicts in emit order (deletes first, then creates oldest-first, then updates)."""
    prev_by_id = {e.id: e for e in prev_window}
    current_by_id = {m["id"]: m for m in current_messages}

    events: list[dict] = []

    # Deletes
    if current_by_id:
        min_id = min(current_by_id.keys())
        max_id = max(current_by_id.keys())
    else:
        min_id = max_id = None

    for prev_id, prev_entry in prev_by_id.items():
        if prev_id in current_by_id:
            continue
        confirmed = False
        if min_id is None:
            # Channel empty now — anything we had is gone
            confirmed = True
        elif prev_id > max_id:
            confirmed = True
        elif min_id < prev_id < max_id:
            confirmed = True
        else:  # prev_id < min_id
            if window_full:
                confirmed = verify_deleted(prev_id)
            else:
                # Window not full → channel is fully captured; missing means deleted
                confirmed = True
        if confirmed:
            events.append({
                "event": "message.delete",
                "channel_id": None,  # filled in by caller
                "guild_id": None,
                "message_id": prev_id,
                "last_known_content": None,
            })

    # Creates (oldest first — Discord returns newest first, so iterate in id order)
    new_ids = sorted(set(current_by_id.keys()) - set(prev_by_id.keys()))
    for nid in new_ids:
        m = current_by_id[nid]
        events.append({
            "event": "message.create",
            "channel_id": None,
            "guild_id": None,
            "message": _build_message_payload(m),
            "attachments": m.get("attachments", []),  # raw — filled/downloaded by caller
        })

    # Updates
    for mid, m in current_by_id.items():
        if mid not in prev_by_id:
            continue
        prev = prev_by_id[mid]
        new_hash = hash_content(m.get("content", ""))
        new_edited = m.get("edited_timestamp")
        if new_hash != prev.content_hash or new_edited != prev.edited_timestamp:
            events.append({
                "event": "message.update",
                "channel_id": None,
                "guild_id": None,
                "message": _build_message_payload(m),
                "attachments": m.get("attachments", []),
            })

    return events
```

- [ ] **Step 4: Run tests, confirm pass**

Run: `pytest tests/test_listener_diff.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add dcli/listener.py tests/test_listener_diff.py
git commit -m "feat: add diff_window for create/update/delete detection"
```

---

## Task 7: Listener poll loop

**Files:**
- Modify: `dcli/listener.py` (append; no behavior change to `diff_window`)

The poll loop owns: per-channel state, first-run seeding, calling `diff_window`, downloading attachments for create/update events, dispatching via `Notifier`, persisting state, SIGINT shutdown.

- [ ] **Step 1: Append `Listener` class to `dcli/listener.py`**

Append to `dcli/listener.py`:

```python
class Listener:
    def __init__(
        self,
        client: DiscordClient,
        notifier: Notifier,
        state: State,
        channel_ids: list[str],
        interval: float = 3.0,
        window: int = 50,
        attachments_dir: Path = Path("attachments"),
        download: bool = True,
    ):
        self._client = client
        self._notifier = notifier
        self._state = state
        self._channels = channel_ids
        self._interval = interval
        self._window = window
        self._attachments_dir = Path(attachments_dir)
        self._download = download
        self._stopping = False

    def _on_sigint(self, *_):
        log.info("shutdown requested")
        self._stopping = True

    def run(self) -> None:
        signal.signal(signal.SIGINT, self._on_sigint)
        signal.signal(signal.SIGTERM, self._on_sigint)

        # Validate token once at startup
        me = self._client.get_current_user()
        log.info("authenticated as %s", me.get("username"))

        log.info("watching %d channel(s) every %.1fs", len(self._channels), self._interval)
        while not self._stopping:
            for cid in self._channels:
                if self._stopping:
                    break
                try:
                    self._poll_channel(cid)
                except Exception as e:
                    log.exception("poll failed for channel %s: %s", cid, e)
            # Sleep in small slices so SIGINT is responsive
            slept = 0.0
            while slept < self._interval and not self._stopping:
                time.sleep(min(0.2, self._interval - slept))
                slept += 0.2
        self._state.save()
        log.info("listener stopped cleanly")

    def _poll_channel(self, channel_id: str) -> None:
        prev = self._state.get_channel(channel_id)
        # Discord returns newest first; we want chronological for our diff
        messages = list(reversed(self._client.get_messages(channel_id, limit=self._window)))

        if prev is None:
            # First run for this channel — seed and emit nothing
            self._state.set_channel(channel_id, [
                WindowEntry(
                    id=m["id"],
                    edited_timestamp=m.get("edited_timestamp"),
                    content_hash=hash_content(m.get("content", "")),
                )
                for m in messages
            ])
            self._state.save()
            log.info("seeded channel %s with %d messages", channel_id, len(messages))
            return

        window_full = len(messages) == self._window

        def verify_deleted(mid: str) -> bool:
            return self._client.get_message(channel_id, mid) is None

        events = diff_window(prev, messages, window_full=window_full, verify_deleted=verify_deleted)

        for ev in events:
            ev["channel_id"] = channel_id
            if ev["event"] in ("message.create", "message.update"):
                raw_atts = ev.pop("attachments", [])
                if self._download and raw_atts:
                    ev["attachments"] = download_attachments(
                        message_id=ev["message"]["id"],
                        attachments=raw_atts,
                        base_dir=self._attachments_dir,
                    )
                else:
                    ev["attachments"] = [
                        {
                            "filename": a.get("filename"),
                            "url": a.get("url"),
                            "local_path": None,
                            "content_type": a.get("content_type"),
                            "size": a.get("size"),
                        }
                        for a in raw_atts
                    ]
            self._notifier.send(ev)

        # Update state with the new window
        self._state.set_channel(channel_id, [
            WindowEntry(
                id=m["id"],
                edited_timestamp=m.get("edited_timestamp"),
                content_hash=hash_content(m.get("content", "")),
            )
            for m in messages
        ])
        self._state.save()
```

- [ ] **Step 2: Make sure the existing diff tests still pass**

Run: `pytest tests/test_listener_diff.py -v`
Expected: 9 passed.

- [ ] **Step 3: Commit**

```bash
git add dcli/listener.py
git commit -m "feat: add Listener poll loop with first-run seeding and SIGINT shutdown"
```

---

## Task 8: Click CLI

**Files:**
- Create: `dcli/cli.py`

Wires everything together. Five commands. Loads `.env`. CLI flags override env.

- [ ] **Step 1: Implement `dcli/cli.py`**

```python
import json
import logging
import os
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

from dcli.client import DiscordAuthError, DiscordClient
from dcli.listener import Listener
from dcli.notifier import Notifier
from dcli.state import State


def _load_env() -> None:
    load_dotenv()


def _require_token() -> str:
    tok = os.environ.get("DISCORD_TOKEN")
    if not tok:
        click.echo("error: DISCORD_TOKEN not set (in env or .env)", err=True)
        sys.exit(2)
    return tok


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Debug logging.")
def main(verbose: bool):
    """dcli — Discord user-account CLI."""
    _load_env()
    _setup_logging(verbose)


@main.command()
@click.argument("channel_ids", nargs=-1, required=True)
@click.option("--interval", default=3.0, show_default=True, help="Poll interval (seconds).")
@click.option("--window", default=50, show_default=True, help="Rolling window size per channel.")
@click.option("--webhook", default=None, help="Webhook URL (overrides WEBHOOK_URL env).")
@click.option("--no-download", is_flag=True, help="Skip attachment download; URL-only payload.")
@click.option("--state-file", default=".dcli-state.json", show_default=True)
@click.option("--attachments-dir", default="attachments", show_default=True)
@click.option("--failures-file", default=".dcli-failed-deliveries.jsonl", show_default=True)
def listen(channel_ids, interval, window, webhook, no_download, state_file, attachments_dir, failures_file):
    """Watch CHANNEL_IDS and POST events to the webhook."""
    token = _require_token()
    webhook_url = webhook or os.environ.get("WEBHOOK_URL")
    if not webhook_url:
        click.echo("error: --webhook or WEBHOOK_URL must be set", err=True)
        sys.exit(2)

    client = DiscordClient(token=token)
    notifier = Notifier(webhook_url=webhook_url, failures_path=Path(failures_file))
    state = State.load(Path(state_file))

    listener = Listener(
        client=client,
        notifier=notifier,
        state=state,
        channel_ids=list(channel_ids),
        interval=interval,
        window=window,
        attachments_dir=Path(attachments_dir),
        download=not no_download,
    )
    try:
        listener.run()
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()
        notifier.close()


@main.command()
@click.argument("channel_id")
@click.option("--limit", default=50, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output raw JSON.")
def fetch(channel_id, limit, as_json):
    """One-shot fetch of last LIMIT messages."""
    token = _require_token()
    client = DiscordClient(token=token)
    try:
        msgs = client.get_messages(channel_id, limit=min(limit, 100))
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()
    if as_json:
        click.echo(json.dumps(list(reversed(msgs)), indent=2))
        return
    for m in reversed(msgs):
        author = m["author"].get("global_name") or m["author"]["username"]
        click.echo(f"{author}: {m.get('content', '')}")


@main.command()
@click.argument("channel_id")
@click.argument("message")
def send(channel_id, message):
    """Send MESSAGE to CHANNEL_ID. Pass '-' to read from stdin."""
    token = _require_token()
    if message == "-":
        message = sys.stdin.read()
    client = DiscordClient(token=token)
    try:
        result = client.send_message(channel_id, message)
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()
    click.echo(f"sent: id={result['id']}")


@main.command()
@click.option("--guild", default=None, help="Filter to one guild id.")
def channels(guild):
    """List guilds and their text channels."""
    token = _require_token()
    client = DiscordClient(token=token)
    try:
        guilds = client.list_guilds()
        if guild:
            guilds = [g for g in guilds if g["id"] == guild]
        for g in guilds:
            click.echo(f"[{g['id']}] {g['name']}")
            for ch in client.list_guild_channels(g["id"]):
                if ch.get("type") != 0:
                    continue  # text channels only
                click.echo(f"  {ch['id']}  #{ch['name']}")
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()


@main.command()
def dms():
    """List active DM channels."""
    token = _require_token()
    client = DiscordClient(token=token)
    try:
        for dm in client.list_dms():
            recipients = ", ".join(
                r.get("global_name") or r.get("username", "?")
                for r in dm.get("recipients", [])
            )
            click.echo(f"{dm['id']}  {recipients}")
    except DiscordAuthError as e:
        click.echo(f"fatal: {e}", err=True)
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify CLI loads**

Run: `dcli --help`
Expected: usage banner showing `listen`, `fetch`, `send`, `channels`, `dms`.

Run: `dcli listen --help`
Expected: `--interval`, `--window`, `--webhook`, `--no-download` flags visible.

- [ ] **Step 3: Run full test suite**

Run: `pytest -v`
Expected: 34 passed (11 client + 5 state + 5 attachments + 4 notifier + 9 listener_diff).

- [ ] **Step 4: Commit**

```bash
git add dcli/cli.py
git commit -m "feat: add click CLI with listen/fetch/send/channels/dms commands"
```

---

## Task 9: End-to-end smoke instructions

**Files:**
- Modify: `README.md` — add a smoke test section

This is for the user to manually verify against real Discord. No automated test against the live API.

- [ ] **Step 1: Append smoke test section to `README.md`**

Append:

```markdown
## Smoke test

In one terminal, run a trivial webhook receiver:

    python -c "
    from http.server import BaseHTTPRequestHandler, HTTPServer
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get('content-length', 0))
            print(self.rfile.read(n).decode())
            self.send_response(204); self.end_headers()
    HTTPServer(('127.0.0.1', 8787), H).serve_forever()
    "

In another:

    dcli channels                                    # find a channel id
    dcli fetch <channel_id> --limit 5                # sanity check
    dcli listen <channel_id>                         # post a message in Discord, watch it print

Post a message, edit it, delete it — each should produce a `message.create`,
`message.update`, then `message.delete` JSON line on the receiver's stdout.
Attach an image — `attachments/<msg_id>/<filename>` should appear locally and
the payload's `local_path` should point at it.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add smoke test instructions"
```

---

## Self-review

1. **Spec coverage:** Listen (T6+T7+T8), fetch (T8), send (T8), channels (T8), dms (T8), webhook payload (T6+T7), attachment download with sanitization (T4), idempotency (T4), state persistence (T3), atomic writes (T3), corrupt recovery (T3), 401/429/5xx (T2), failed-delivery buffer (T5), SIGINT (T7), first-run seeding (T7), three delete cases — gap inside / past top / off bottom (T6). All present.

2. **Placeholder scan:** No TBD/TODO. All steps include code or exact commands.

3. **Type consistency:** `WindowEntry(id, edited_timestamp, content_hash)` defined in T3, used identically in T6, T7. `hash_content()` defined in T6, used in T7. `download_attachments(message_id, attachments, base_dir, client=None)` defined in T4, called same way in T7. `Notifier(webhook_url, failures_path)` defined in T5, used same way in T8. Method names (`get_messages`, `get_message`, `send_message`, `list_guilds`, `list_guild_channels`, `list_dms`, `get_current_user`) consistent across T2/T7/T8.
