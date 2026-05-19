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
