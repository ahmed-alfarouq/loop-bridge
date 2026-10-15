"""Desktop-side outbox: queue OpenCode responses for Firefox pickup.

Pull-based handoff — the extension fetches on explicit user action, so there
is no polling, no socket, and no database. One ``*.ready.json`` file per
completed exchange; the native host marks it delivered (``*.done.json``)
only after the extension acknowledges receipt.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

RESPONSE_TYPE = "loopbridge.response"
MAX_RESPONSE_CHARS = 100_000  # model output cap for the return trip
READY_SUFFIX = ".ready.json"
REQUEST_ID_PATTERN = re.compile(r"[A-Za-z0-9-]{1,64}")


def outbox_dir() -> Path:
    """Per-user outbox. Env override exists for tests."""
    override = os.environ.get("LOOPBRIDGE_OUTBOX_DIR")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local_app_data) / "LoopBridge" / "outbox"


def ensure_outbox() -> Path:
    directory = outbox_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def check_request_id(request_id: object) -> str:
    if not isinstance(request_id, str) or not REQUEST_ID_PATTERN.fullmatch(request_id):
        raise ValueError(f"invalid request id: {request_id!r}")
    return request_id


def write_response(
    request_id: str, tab_id: int, text: str, session_id: str | None = None
) -> Path:
    """Queue one response. Raises ValueError on invalid/oversized payloads."""
    check_request_id(request_id)
    if not isinstance(tab_id, int) or isinstance(tab_id, bool) or tab_id < 0:
        raise ValueError(f"invalid tab id: {tab_id!r}")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("response text is empty")
    if len(text) > MAX_RESPONSE_CHARS:
        raise ValueError(f"response too large for return trip: {len(text)} chars")
    ensure_outbox()
    path = outbox_dir() / f"resp-{request_id}{READY_SUFFIX}"
    payload = {
        "type": RESPONSE_TYPE,
        "requestId": request_id,
        "tabId": tab_id,
        "text": text,
        "sessionId": session_id,
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)
    return path
