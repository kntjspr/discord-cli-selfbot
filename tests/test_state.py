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
