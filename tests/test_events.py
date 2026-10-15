"""Tests for OpenCode NDJSON event parsing (no subprocess, no quota)."""
import json

import pytest

from loopbridge.opencode import events


def _line(obj) -> str:
    return json.dumps(obj)


STEP_START = {
    "type": "step_start",
    "timestamp": 1792081661064,
    "sessionID": "ses_abc123",
    "part": {
        "id": "prt_1",
        "sessionID": "ses_abc123",
        "messageID": "msg_1",
        "type": "step-start",
    },
}

TEXT_EVENT = {
    "type": "text",
    "timestamp": 1792081661340,
    "sessionID": "ses_abc123",
    "part": {
        "id": "prt_2",
        "sessionID": "ses_abc123",
        "messageID": "msg_1",
        "type": "text",
        "text": "LOOPBRIDGE-PROBE-OK",
        "time": {"start": 1, "end": 2},
    },
}

ERROR_EVENT = {
    "type": "error",
    "timestamp": 1792081457232,
    "sessionID": "",
    "error": {"type": "unknown", "message": 'Expected a string starting with "ses"'},
}


def test_happy_path_extracts_session_and_text():
    raw = ("\n".join([_line(STEP_START), _line(TEXT_EVENT)]) + "\n").encode("utf-8")
    parsed, encoding = parsed_or_fail(raw)
    assert encoding == "utf-8"
    assert parsed.session_id == "ses_abc123"
    assert parsed.texts == ["LOOPBRIDGE-PROBE-OK"]
    assert parsed.final_text == "LOOPBRIDGE-PROBE-OK"
    ok, message = events.classify(parsed, exit_code=0, timed_out=False)
    assert ok and message == "OK"


def parsed_or_fail(raw: bytes):
    return events.parse_ndjson(raw)


def test_error_event_fails_classification():
    raw = (_line(ERROR_EVENT) + "\n").encode("utf-8")
    parsed, _ = events.parse_ndjson(raw)
    assert parsed.error_events and parsed.session_id is None and not parsed.texts
    ok, message = events.classify(parsed, exit_code=1, timed_out=False)
    assert not ok and "ses" in message


def test_malformed_line_recorded_and_fails():
    raw = (_line(STEP_START) + "\n{not json\n" + _line(TEXT_EVENT) + "\n").encode("utf-8")
    parsed, _ = events.parse_ndjson(raw)
    assert parsed.malformed_lines == [2]
    assert parsed.texts == ["LOOPBRIDGE-PROBE-OK"]
    ok, _ = events.classify(parsed, exit_code=0, timed_out=False)
    assert not ok  # partial output must not count as success


def test_empty_output_is_incomplete_not_success():
    parsed, _ = events.parse_ndjson(b"")
    assert parsed.events == [] and parsed.session_id is None
    ok, message = events.classify(parsed, exit_code=0, timed_out=False)
    assert not ok and "no assistant text" in message


def test_unknown_event_type_tolerated_but_success_requires_text():
    unknown = {"type": "future_event", "sessionID": "ses_x", "part": {}}
    raw = (_line(unknown) + "\n").encode("utf-8")
    parsed, _ = events.parse_ndjson(raw)
    assert parsed.unknown_types == ["future_event"]
    ok, _ = events.classify(parsed, exit_code=0, timed_out=False)
    assert not ok


def test_nonzero_exit_fails_even_with_text():
    raw = (_line(TEXT_EVENT) + "\n").encode("utf-8")
    parsed, _ = events.parse_ndjson(raw)
    ok, message = events.classify(parsed, exit_code=1, timed_out=False)
    assert not ok and "code 1" in message


def test_timeout_fails_with_no_retry_guidance():
    raw = (_line(TEXT_EVENT) + "\n").encode("utf-8")
    parsed, _ = events.parse_ndjson(raw)
    ok, message = events.classify(parsed, exit_code=0, timed_out=True)
    assert not ok and "Do not resend blindly" in message


def test_undecodable_bytes_raise():
    with pytest.raises(ValueError):
        events.parse_ndjson(b"\xff\x00\xfe\x01binary")


def test_utf16_bom_decoded():
    raw = (_line(TEXT_EVENT) + "\n").encode("utf-16")
    parsed, encoding = events.parse_ndjson(raw)
    assert "utf-16" in encoding
    assert parsed.texts == ["LOOPBRIDGE-PROBE-OK"]
