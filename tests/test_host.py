"""Tests for the Firefox native-messaging host.

The host script is executed for real (framed stdin, parsed stdout) with an
isolated inbox dir. No OpenCode process is ever involved: the host module
must not even be capable of spawning one.
"""
import json
import struct
import subprocess
import sys
from pathlib import Path

HOST_SCRIPT = Path(__file__).resolve().parent.parent / "hosts" / "loopbridge_host.py"
MAX_TEXT_CHARS = 32000


def frame(obj) -> bytes:
    payload = json.dumps(obj).encode("utf-8")
    return struct.pack("<I", len(payload)) + payload


def run_host(raw_stdin: bytes, inbox_dir: Path, outbox_dir=None):
    import os

    resolved_outbox = str(outbox_dir) if outbox_dir is not None else str(inbox_dir.parent / "outbox")
    env = dict(
        os.environ,
        LOOPBRIDGE_INBOX_DIR=str(inbox_dir),
        LOOPBRIDGE_OUTBOX_DIR=resolved_outbox,
    )
    return subprocess.run(
        [sys.executable, "-u", str(HOST_SCRIPT)],
        input=raw_stdin,
        capture_output=True,
        timeout=60,
        env=env,
    )


def read_ack(proc) -> dict:
    assert len(proc.stdout) >= 4, f"host wrote no framed ack: rc={proc.returncode}"
    (length,) = struct.unpack("<I", proc.stdout[:4])
    return json.loads(proc.stdout[4 : 4 + length].decode("utf-8"))


def inbox_files(inbox_dir: Path):
    return sorted(inbox_dir.glob("*.ready.json"))


def test_valid_selection_stored_and_acked(tmp_path):
    inbox = tmp_path / "inbox"
    proc = run_host(frame({"type": "loopbridge.selection", "text": "hello bridge"}), inbox)
    assert proc.returncode == 0
    assert read_ack(proc) == {"ok": True, "requestId": None}
    files = inbox_files(inbox)
    assert len(files) == 1
    stored = json.loads(files[0].read_text(encoding="utf-8"))
    assert stored == {"type": "loopbridge.selection", "text": "hello bridge"}


def test_empty_text_rejected_without_inbox_write(tmp_path):
    inbox = tmp_path / "inbox"
    for bad in ("", "   "):
        proc = run_host(frame({"type": "loopbridge.selection", "text": bad}), inbox)
        assert proc.returncode == 1
        assert read_ack(proc)["ok"] is False
    assert inbox_files(inbox) == []


def test_oversized_text_rejected(tmp_path):
    inbox = tmp_path / "inbox"
    proc = run_host(
        frame({"type": "loopbridge.selection", "text": "x" * (MAX_TEXT_CHARS + 1)}),
        inbox,
    )
    assert proc.returncode == 1
    assert read_ack(proc)["ok"] is False
    assert inbox_files(inbox) == []


def test_unexpected_type_rejected(tmp_path):
    inbox = tmp_path / "inbox"
    proc = run_host(frame({"type": "loopbridge.run", "text": "do stuff"}), inbox)
    assert proc.returncode == 1
    ack = read_ack(proc)
    assert ack["ok"] is False and "type" in ack["error"]
    assert inbox_files(inbox) == []


def test_malformed_framing_rejected(tmp_path):
    inbox = tmp_path / "inbox"
    proc = run_host(b"\x05\x00", inbox)  # truncated header
    assert proc.returncode == 1
    assert not inbox.exists() or inbox_files(inbox) == []


def test_non_object_json_rejected(tmp_path):
    inbox = tmp_path / "inbox"
    proc = run_host(frame(["not", "an", "object"]), inbox)
    assert proc.returncode == 1
    assert inbox_files(inbox) == []


def test_host_cannot_launch_processes():
    source = HOST_SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("subprocess", "os.system", "os.exec", "os.spawn", "os.popen", "socket"):
        assert forbidden not in source, f"host must not use {forbidden}"


def seed_response(outbox: Path, request_id: str, tab_id: int, text: str = "answer"):
    outbox.mkdir(parents=True, exist_ok=True)
    payload = {
        "type": "loopbridge.response",
        "requestId": request_id,
        "tabId": tab_id,
        "text": text,
        "sessionId": "ses-1",
    }
    (outbox / f"resp-{request_id}.ready.json").write_text(json.dumps(payload), encoding="utf-8")


def test_fetch_returns_oldest_for_tab_only(tmp_path):
    outbox = tmp_path / "outbox"
    seed_response(outbox, "req-a", 11, text="first")
    seed_response(outbox, "req-b", 22, text="other-tab")
    seed_response(outbox, "req-c", 11, text="second")
    proc = run_host(
        frame({"type": "loopbridge.fetch_result", "tabId": 11}),
        tmp_path / "inbox",
        outbox,
    )
    assert proc.returncode == 0
    reply = read_ack(proc)
    assert reply["ok"] is True
    assert reply["response"]["requestId"] == "req-a"
    assert reply["response"]["text"] == "first"
    assert reply["other_pending"] == 2  # req-b (other tab) + req-c (same tab, queued)
    # Nothing marked delivered by a fetch
    assert (outbox / "resp-req-a.ready.json").exists()


def test_fetch_unknown_tab_returns_null_with_pending_hint(tmp_path):
    outbox = tmp_path / "outbox"
    seed_response(outbox, "req-a", 11)
    proc = run_host(
        frame({"type": "loopbridge.fetch_result", "tabId": 99}),
        tmp_path / "inbox",
        outbox,
    )
    assert proc.returncode == 0
    reply = read_ack(proc)
    assert reply == {"ok": True, "response": None, "other_pending": 1}


def test_ack_marks_delivered_and_second_fetch_moves_on(tmp_path):
    outbox = tmp_path / "outbox"
    seed_response(outbox, "req-a", 11, text="first")
    seed_response(outbox, "req-c", 11, text="second")
    inbox = tmp_path / "inbox"
    first = read_ack(run_host(frame({"type": "loopbridge.fetch_result", "tabId": 11}), inbox, outbox))
    assert first["response"]["requestId"] == "req-a"
    ack = read_ack(run_host(frame({"type": "loopbridge.ack_delivery", "requestId": "req-a"}), inbox, outbox))
    assert ack == {"ok": True, "delivered": True}
    assert (outbox / "resp-req-a.done.json").exists()
    second = read_ack(run_host(frame({"type": "loopbridge.fetch_result", "tabId": 11}), inbox, outbox))
    assert second["response"]["requestId"] == "req-c"


def test_duplicate_ack_is_unmatched_not_silent(tmp_path):
    outbox = tmp_path / "outbox"
    seed_response(outbox, "req-a", 11)
    inbox = tmp_path / "inbox"
    run_host(frame({"type": "loopbridge.ack_delivery", "requestId": "req-a"}), inbox, outbox)
    dup = read_ack(run_host(frame({"type": "loopbridge.ack_delivery", "requestId": "req-a"}), inbox, outbox))
    assert dup["ok"] is False and "already-delivered" in dup["error"]
    unknown = read_ack(
        run_host(frame({"type": "loopbridge.ack_delivery", "requestId": "nope"}), inbox, outbox)
    )
    assert unknown["ok"] is False


def test_malformed_and_oversized_fetch_rejected(tmp_path):
    outbox = tmp_path / "outbox"
    bad_tab = read_ack(
        run_host(frame({"type": "loopbridge.fetch_result", "tabId": "11"}), tmp_path / "inbox", outbox)
    )
    assert bad_tab["ok"] is False
    seed_response(outbox, "req-big", 11, text="x" * (100_000 + 1))
    big = read_ack(
        run_host(frame({"type": "loopbridge.fetch_result", "tabId": 11}), tmp_path / "inbox", outbox)
    )
    assert big["ok"] is False and "too large" in big["error"]


def test_selection_carries_routing_but_old_shape_still_accepted(tmp_path):
    inbox = tmp_path / "inbox"
    proc = run_host(
        frame({"type": "loopbridge.selection", "text": "hi", "requestId": "abc-123", "tabId": 5}),
        inbox,
        tmp_path / "outbox",
    )
    assert proc.returncode == 0
    assert read_ack(proc) == {"ok": True, "requestId": "abc-123"}
    stored = json.loads(inbox_files(inbox)[0].read_text(encoding="utf-8"))
    assert stored["requestId"] == "abc-123" and stored["tabId"] == 5
    legacy = run_host(frame({"type": "loopbridge.selection", "text": "old"}), inbox, tmp_path / "outbox")
    assert read_ack(legacy) == {"ok": True, "requestId": None}
