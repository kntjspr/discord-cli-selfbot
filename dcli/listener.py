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

    if current_by_id:
        min_id = min(current_by_id.keys())
        max_id = max(current_by_id.keys())
    else:
        min_id = max_id = None

    # Deletes
    for prev_id, prev_entry in prev_by_id.items():
        if prev_id in current_by_id:
            continue
        confirmed = False
        if min_id is None:
            confirmed = True
        elif prev_id > max_id:
            confirmed = True
        elif min_id < prev_id < max_id:
            confirmed = True
        else:  # prev_id < min_id
            if window_full:
                confirmed = verify_deleted(prev_id)
            else:
                confirmed = True
        if confirmed:
            events.append({
                "event": "message.delete",
                "channel_id": None,
                "guild_id": None,
                "message_id": prev_id,
                "last_known_content": None,
            })

    # Creates (oldest first)
    new_ids = sorted(set(current_by_id.keys()) - set(prev_by_id.keys()))
    for nid in new_ids:
        m = current_by_id[nid]
        events.append({
            "event": "message.create",
            "channel_id": None,
            "guild_id": None,
            "message": _build_message_payload(m),
            "attachments": m.get("attachments", []),
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
            slept = 0.0
            while slept < self._interval and not self._stopping:
                time.sleep(min(0.2, self._interval - slept))
                slept += 0.2
        self._state.save()
        log.info("listener stopped cleanly")

    def _poll_channel(self, channel_id: str) -> None:
        prev = self._state.get_channel(channel_id)
        messages = list(reversed(self._client.get_messages(channel_id, limit=self._window)))

        if prev is None:
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

        self._state.set_channel(channel_id, [
            WindowEntry(
                id=m["id"],
                edited_timestamp=m.get("edited_timestamp"),
                content_hash=hash_content(m.get("content", "")),
            )
            for m in messages
        ])
        self._state.save()
