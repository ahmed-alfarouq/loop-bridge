"""Firefox-selection inbox: smallest local handoff to the desktop app.

The native host drops one ``*.ready.json`` file per accepted selection into
the inbox directory; the UI watches the directory and adopts new files.
No network, no broker, no database. Files are validated here — never
trusted blindly — and renamed to ``*.done.json`` after adoption so each
selection is processed exactly once per client run.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

MESSAGE_TYPE = "loopbridge.selection"
MAX_TEXT_CHARS = 32000  # must match extension/background.js and hosts/loopbridge_host.py
READY_SUFFIX = ".ready.json"
DONE_SUFFIX = ".done.json"
REQUEST_ID_RE = re.compile(r"[A-Za-z0-9-]{1,64}")


@dataclass(frozen=True)
class InboxRequest:
    """One adopted selection with routing info (tab may be unknown)."""

    text: str
    request_id: str | None
    tab_id: int | None


def _valid_tab_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _valid_request_id(value: object) -> str | None:
    if isinstance(value, str) and REQUEST_ID_RE.fullmatch(value):
        return value
    return None


def inbox_dir() -> Path:
    """Per-user inbox. Env override exists for tests."""
    override = os.environ.get("LOOPBRIDGE_INBOX_DIR")
    if override:
        return Path(override)
    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(local_app_data) / "LoopBridge" / "inbox"


def validate_payload(obj: object) -> tuple[bool, str]:
    """Validate one decoded inbox object. Returns ``(ok, text_or_error)``."""
    ok, result = validate_request(obj)
    if not ok:
        assert isinstance(result, str)
        return False, result
    return True, result.text


def validate_request(obj: object) -> tuple[bool, InboxRequest | str]:
    """Validate routing + text. Returns ``(True, InboxRequest)`` or ``(False, error)``."""
    if not isinstance(obj, dict):
        return False, "inbox file must contain a JSON object"
    if obj.get("type") != MESSAGE_TYPE:
        return False, f"unexpected message type: {obj.get('type')!r}"
    text = obj.get("text")
    if not isinstance(text, str) or not text.strip():
        return False, "selection text is empty"
    if len(text) > MAX_TEXT_CHARS:
        return False, f"selection too large: {len(text)} chars"
    return True, InboxRequest(
        text=text,
        request_id=_valid_request_id(obj.get("requestId")),
        tab_id=_valid_tab_id(obj.get("tabId")),
    )


def load_inbox_file(path: Path) -> tuple[bool, str]:
    """Read + validate one inbox file. Never raises on bad content."""
    ok, payload = load_request(path)
    if not ok:
        assert isinstance(payload, str)
        return False, payload
    return True, payload.text


def load_request(path: Path) -> tuple[bool, InboxRequest | str]:
    """Read + validate one inbox file with routing info preserved."""
    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"unreadable inbox file {path.name}: {exc}"
    return validate_request(obj)


def scan(directory: Path) -> list[Path]:
    """List unprocessed inbox files, oldest first."""
    if not directory.is_dir():
        return []
    return sorted(directory.glob(f"*{READY_SUFFIX}"))


def mark_done(path: Path) -> Path:
    """Rename an adopted file so it is not processed again."""
    done = path.with_name(path.name[: -len(READY_SUFFIX)] + DONE_SUFFIX)
    path.replace(done)
    return done


def ensure_inbox() -> Path:
    directory = inbox_dir()
    directory.mkdir(parents=True, exist_ok=True)
    return directory
