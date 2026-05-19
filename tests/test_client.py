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
    assert req.read() == b'{"content":"hello"}'


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
