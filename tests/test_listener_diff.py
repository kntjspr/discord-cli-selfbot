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
    events = diff_window([], [_msg("1", "hi")], window_full=False, verify_deleted=lambda _id: False)
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
    called = []
    def verify(mid):
        called.append(mid)
        return True
    events = diff_window(prev, current, window_full=False, verify_deleted=verify)
    assert [e["event"] for e in events] == ["message.delete"]
    assert events[0]["message_id"] == "2"
    assert events[0]["last_known_content"] is None
    assert called == []


def test_missing_id_past_top_is_confirmed_delete():
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
    current = [_msg("2", "b"), _msg("3", "c")]
    verified = []
    def verify(mid):
        verified.append(mid)
        return False
    events = diff_window(prev, current, window_full=True, verify_deleted=verify)
    assert [e["event"] for e in events] == ["message.create"]
    assert verified == ["1"]


def test_missing_id_off_bottom_when_window_full_and_verified_deleted():
    prev = [
        WindowEntry(id="1", edited_timestamp=None, content_hash=hash_content("a")),
        WindowEntry(id="2", edited_timestamp=None, content_hash=hash_content("b")),
    ]
    current = [_msg("2", "b"), _msg("3", "c")]
    events = diff_window(prev, current, window_full=True, verify_deleted=lambda _id: True)
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
