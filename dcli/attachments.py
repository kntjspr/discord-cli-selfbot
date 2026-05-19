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
