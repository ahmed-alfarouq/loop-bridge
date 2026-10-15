"""Tests for request/response association (pure logic, no Qt, no quota)."""
from loopbridge.exchange import ExchangeTracker, Request


def _tracker_two_tabs():
    tracker = ExchangeTracker()
    tracker.adopt(Request(request_id="req-a", tab_id=11, text="first"))
    tracker.adopt(Request(request_id="req-b", tab_id=22, text="second"))
    return tracker


def test_responses_bind_to_the_run_request_not_the_latest():
    tracker = _tracker_two_tabs()
    # User displayed req-a again? current is req-b; run binds *displayed* one.
    assert tracker.begin_run() == "req-b"
    assert tracker.finish_run("answer-b", "ses-1", ok=True) is True
    sendable = tracker.sendable()
    assert sendable is not None and sendable.tab_id == 22
    assert sendable.response == "answer-b"
    # req-a has no response: nothing sendable for it
    tracker.current_id = "req-a"
    assert tracker.sendable() is None


def test_duplicate_completion_ignored():
    tracker = _tracker_two_tabs()
    tracker.begin_run()
    assert tracker.finish_run("answer", "ses-1", ok=True) is True
    assert tracker.finish_run("answer-again", "ses-1", ok=True) is False
    assert tracker.completed["req-b"].response == "answer"


def test_unmatched_completion_ignored():
    tracker = ExchangeTracker()
    assert tracker.finish_run("stray", "ses-9", ok=True) is False
    assert tracker.completed == {}
    assert tracker.sendable() is None


def test_failed_run_queues_nothing():
    tracker = _tracker_two_tabs()
    tracker.begin_run()
    assert tracker.finish_run("", None, ok=False) is False
    assert tracker.sendable() is None


def test_unknown_tab_not_routable():
    tracker = ExchangeTracker()
    tracker.adopt(Request(request_id="legacy", tab_id=None, text="old"))
    tracker.begin_run()
    assert tracker.finish_run("answer", "ses-2", ok=True) is True
    assert tracker.sendable() is None  # recorded, but cannot route


def test_unrun_count_tracks_pending():
    tracker = _tracker_two_tabs()
    assert tracker.unrun_count() == 2
    tracker.begin_run()
    tracker.finish_run("answer-b", "ses-1", ok=True)
    assert tracker.unrun_count() == 1
