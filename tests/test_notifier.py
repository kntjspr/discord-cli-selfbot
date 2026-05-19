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
