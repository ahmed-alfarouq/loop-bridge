"""Tests for desktop-side inbox validation (no processes, no quota)."""
import json

from loopbridge import inbox as inbox_store


def _write(path, obj) -> None:
    path.write_text(json.dumps(obj), encoding="utf-8")


def test_valid_payload_adopted(tmp_path):
    target = tmp_path / "sel.ready.json"
    _write(target, {"type": "loopbridge.selection", "text": "hello"})
    ok, text = inbox_store.load_inbox_file(target)
    assert (ok, text) == (True, "hello")


def test_empty_and_oversized_rejected(tmp_path):
    empty = tmp_path / "a.ready.json"
    _write(empty, {"type": "loopbridge.selection", "text": "  "})
    assert inbox_store.load_inbox_file(empty)[0] is False

    big = tmp_path / "b.ready.json"
    _write(big, {"type": "loopbridge.selection", "text": "x" * (inbox_store.MAX_TEXT_CHARS + 1)})
    ok, error = inbox_store.load_inbox_file(big)
    assert ok is False and "too large" in error


def test_wrong_type_and_garbage_rejected(tmp_path):
    wrong = tmp_path / "c.ready.json"
    _write(wrong, {"type": "something.else", "text": "hi"})
    assert inbox_store.load_inbox_file(wrong)[0] is False

    garbage = tmp_path / "d.ready.json"
    garbage.write_text("{not json", encoding="utf-8")
    assert inbox_store.load_inbox_file(garbage)[0] is False


def test_scan_and_mark_done_are_exactly_once(tmp_path):
    first = tmp_path / "a.ready.json"
    second = tmp_path / "b.ready.json"
    _write(first, {"type": "loopbridge.selection", "text": "one"})
    _write(second, {"type": "loopbridge.selection", "text": "two"})
    assert [p.name for p in inbox_store.scan(tmp_path)] == ["a.ready.json", "b.ready.json"]
    inbox_store.mark_done(first)
    assert [p.name for p in inbox_store.scan(tmp_path)] == ["b.ready.json"]
    assert (tmp_path / "a.done.json").exists()


def test_routing_info_preserved_when_present(tmp_path):
    target = tmp_path / "sel.ready.json"
    _write(
        target,
        {"type": "loopbridge.selection", "text": "hi", "requestId": "abc-1", "tabId": 9},
    )
    ok, request = inbox_store.load_request(target)
    assert ok and request.request_id == "abc-1" and request.tab_id == 9


def test_routing_absent_or_invalid_yields_unknown_tab(tmp_path):
    legacy = tmp_path / "old.ready.json"
    _write(legacy, {"type": "loopbridge.selection", "text": "hi"})
    ok, request = inbox_store.load_request(legacy)
    assert ok and request.request_id is None and request.tab_id is None

    bad = tmp_path / "bad.ready.json"
    _write(bad, {"type": "loopbridge.selection", "text": "hi", "requestId": "../x", "tabId": -2})
    ok, request = inbox_store.load_request(bad)
    assert ok and request.text == "hi"
    assert request.request_id is None and request.tab_id is None
