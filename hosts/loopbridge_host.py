#!/usr/bin/env python3
"""LoopBridge Firefox native-messaging host (stdlib only, no dependencies).

Protocol (per MDN native messaging): each message is UTF-8 JSON preceded by
an unsigned 32-bit little-endian length. Reads ONE message from stdin,
handles it, writes ONE framed reply to stdout, and exits.

Messages handled (all validated; anything else is rejected):

- {"type": "loopbridge.selection", "text": str, "requestId"?: str,
   "tabId"?: int} — stores the selection in the inbox, replies
  {"ok": true, "requestId": ...}. ``requestId``/``tabId`` route the later
  response; when absent the text is still accepted but cannot be routed.
- {"type": "loopbridge.fetch_result", "tabId": int} — returns the oldest
  undelivered outbox response for that tab:
  {"ok": true, "response": {...} | None, "other_pending": int}.
  Nothing is marked delivered here.
- {"type": "loopbridge.ack_delivery", "requestId": str} — marks the
  response delivered (at-most-once per ack; the extension dedups).

This host NEVER launches OpenCode, NEVER executes anything, NEVER opens a
network listener, and NEVER reads project files.
"""

from __future__ import annotations

import json
import os
import re
import struct
import sys
import tempfile
import time

SELECTION_TYPE = "loopbridge.selection"
FETCH_TYPE = "loopbridge.fetch_result"
ACK_TYPE = "loopbridge.ack_delivery"
RESPONSE_TYPE = "loopbridge.response"
KNOWN_TYPES = frozenset({SELECTION_TYPE, FETCH_TYPE, ACK_TYPE})

MAX_TEXT_CHARS = 32000
MAX_RESPONSE_CHARS = 100_000
MAX_MESSAGE_BYTES = 1024 * 1024  # hard cap on the framed payload we will read
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")


def app_dir(name: str, env_override: str) -> str:
    override = os.environ.get(env_override)
    if override:
        return override
    local_app_data = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.path.join(local_app_data, "LoopBridge", name)


def inbox_dir() -> str:
    return app_dir("inbox", "LOOPBRIDGE_INBOX_DIR")


def outbox_dir() -> str:
    return app_dir("outbox", "LOOPBRIDGE_OUTBOX_DIR")


def read_exact(stream, count: int) -> bytes:
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            raise EOFError("stdin closed mid-message")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message() -> dict:
    header = read_exact(sys.stdin.buffer, 4)
    (length,) = struct.unpack("<I", header)
    if length == 0 or length > MAX_MESSAGE_BYTES:
        raise ValueError(f"invalid message length: {length}")
    payload = read_exact(sys.stdin.buffer, length)
    obj = json.loads(payload.decode("utf-8"))
    if not isinstance(obj, dict):
        raise ValueError("message must be a JSON object")
    return obj


def valid_request_id(value: object) -> str | None:
    if isinstance(value, str) and REQUEST_ID_RE.fullmatch(value):
        return value
    return None


def valid_tab_id(value: object, *, required: bool) -> int | None:
    if isinstance(value, bool):
        valid = False
    else:
        valid = isinstance(value, int) and value >= 0
    if not valid and required:
        raise ValueError(f"invalid tab id: {value!r}")
    return value if valid else None


def handle_selection(message: dict) -> dict:
    text = message.get("text")
    if not isinstance(text, str) or not text.strip():
        return {"ok": False, "error": "selection text is empty"}
    if len(text) > MAX_TEXT_CHARS:
        return {"ok": False, "error": f"selection too large: {len(text)} chars"}
    request_id = valid_request_id(message.get("requestId"))
    tab_id = valid_tab_id(message.get("tabId"), required=False)
    stored = {"type": SELECTION_TYPE, "text": text}
    if request_id is not None:
        stored["requestId"] = request_id
    if tab_id is not None:
        stored["tabId"] = tab_id
    try:
        path = store_inbox(stored)
    except OSError as exc:
        return {"ok": False, "error": f"inbox write failed: {exc}"}
    _ = path
    return {"ok": True, "requestId": request_id}


def store_inbox(stored: dict) -> str:
    directory = inbox_dir()
    os.makedirs(directory, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"sel-{stamp}-{os.getpid()}-", suffix=".json", dir=directory
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(stored, fh)
        final_path = tmp_path[: -len(".json")] + ".ready.json"
        os.replace(tmp_path, final_path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return final_path


def read_outbox_response(path: str) -> dict | str:
    """Return the validated response dict, or an error string."""
    try:
        with open(path, encoding="utf-8") as fh:
            obj = json.load(fh)
    except (OSError, ValueError) as exc:
        return f"unreadable outbox file: {exc}"
    if not isinstance(obj, dict) or obj.get("type") != RESPONSE_TYPE:
        return "unexpected outbox message type"
    request_id = valid_request_id(obj.get("requestId"))
    tab_id = valid_tab_id(obj.get("tabId"), required=False)
    text = obj.get("text")
    if request_id is None or tab_id is None:
        return "outbox response missing routing info"
    if not isinstance(text, str) or not text.strip():
        return "outbox response text is empty"
    if len(text) > MAX_RESPONSE_CHARS:
        return "outbox response too large"
    return {
        "type": RESPONSE_TYPE,
        "requestId": request_id,
        "tabId": tab_id,
        "text": text,
        "sessionId": obj.get("sessionId"),
    }


def handle_fetch(message: dict) -> dict:
    try:
        tab_id = valid_tab_id(message.get("tabId"), required=True)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    assert tab_id is not None
    directory = outbox_dir()
    try:
        names = sorted(
            name for name in os.listdir(directory) if name.endswith(".ready.json")
        )
    except FileNotFoundError:
        names = []
    except OSError as exc:
        return {"ok": False, "error": f"outbox unreadable: {exc}"}
    match: dict | None = None
    other_pending = 0
    first_error: str | None = None
    for name in names:
        response = read_outbox_response(os.path.join(directory, name))
        if isinstance(response, str):
            if first_error is None:
                first_error = f"{name}: {response}"
            continue
        if response["tabId"] == tab_id and match is None:
            match = response
        else:
            other_pending += 1
    if match is None and first_error is not None and other_pending == 0:
        return {"ok": False, "error": first_error}
    return {"ok": True, "response": match, "other_pending": other_pending}


def handle_ack(message: dict) -> dict:
    request_id = valid_request_id(message.get("requestId"))
    if request_id is None:
        return {"ok": False, "error": "invalid request id"}
    directory = outbox_dir()
    name = f"resp-{request_id}.ready.json"
    path = os.path.join(directory, name)
    if not os.path.isfile(path):
        return {"ok": False, "error": "unknown or already-delivered request"}
    try:
        os.replace(path, os.path.join(directory, f"resp-{request_id}.done.json"))
    except OSError as exc:
        return {"ok": False, "error": f"delivery marking failed: {exc}"}
    return {"ok": True, "delivered": True}


def write_reply(reply: dict) -> None:
    payload = json.dumps(reply).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main() -> int:
    try:
        message = read_message()
    except (EOFError, ValueError, json.JSONDecodeError, struct.error) as exc:
        write_reply({"ok": False, "error": f"invalid message framing: {exc}"})
        return 1
    msg_type = message.get("type")
    if msg_type == SELECTION_TYPE:
        reply = handle_selection(message)
    elif msg_type == FETCH_TYPE:
        reply = handle_fetch(message)
    elif msg_type == ACK_TYPE:
        reply = handle_ack(message)
    else:
        reply = {"ok": False, "error": f"unexpected message type: {msg_type!r}"}
    write_reply(reply)
    return 0 if reply.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
