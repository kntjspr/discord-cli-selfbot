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
