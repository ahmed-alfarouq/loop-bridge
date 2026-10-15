"""Tests for desktop-side outbox writes (no processes, no quota)."""
import json

import pytest

from loopbridge import outbox as outbox_store


def test_write_valid_response(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOPBRIDGE_OUTBOX_DIR", str(tmp_path))
    path = outbox_store.write_response("req-1", 7, "the answer", session_id="ses-1")
    assert path.name == "resp-req-1.ready.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "type": "loopbridge.response",
        "requestId": "req-1",
        "tabId": 7,
        "text": "the answer",
        "sessionId": "ses-1",
    }


def test_rejects_bad_ids_empty_and_oversized(monkeypatch, tmp_path):
    monkeypatch.setenv("LOOPBRIDGE_OUTBOX_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        outbox_store.write_response("../evil", 7, "x")
    with pytest.raises(ValueError):
        outbox_store.write_response("req-1", -1, "x")
    with pytest.raises(ValueError):
        outbox_store.write_response("req-1", True, "x")
    with pytest.raises(ValueError):
        outbox_store.write_response("req-1", 7, "   ")
    with pytest.raises(ValueError):
        outbox_store.write_response("req-1", 7, "x" * (outbox_store.MAX_RESPONSE_CHARS + 1))
    assert list(tmp_path.iterdir()) == []
