"""OpenCode CLI integration: NDJSON event parsing.

Observed v2.0.29 contract (verified by live probe, Phase 1C): ``opencode run
--format json`` writes newline-delimited JSON to stdout, one event per line.
Known event shapes::

    {"type": "step_start", "timestamp": ..., "sessionID": "ses_...",
     "part": {"id": "prt_...", "sessionID": "ses_...",
              "messageID": "msg_...", "type": "step-start"}}
    {"type": "text", ...,
     "part": {"id": "prt_...", "sessionID": "ses_...",
              "messageID": "msg_...", "type": "text",
              "text": "...", "time": {"start": ..., "end": ...}}}
    {"type": "error", "timestamp": ..., "sessionID": "",
     "error": {"type": ..., "message": "..."}}

Anything else is tolerated but reported — never silently treated as success.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

KNOWN_EVENT_TYPES = frozenset({"step_start", "text", "error"})


def decode_output(data: bytes) -> tuple[str, str]:
    """Decode raw stdout bytes, returning ``(text, encoding_note)``.

    Rule: BOM sniff first (UTF-16 LE/BE, UTF-8-SIG), otherwise strict UTF-8.
    Raises :class:`ValueError` on undecodable bytes — callers must fail
    visibly instead of guessing.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16"), "utf-16 (BOM)"
    if data[:3] == b"\xef\xbb\xbf":
        return data.decode("utf-8-sig"), "utf-8-sig (BOM)"
    return data.decode("utf-8"), "utf-8"


@dataclass
class ParsedRun:
    """Structured view of one ``run --format json`` stdout stream."""

    events: list[dict] = field(default_factory=list)
    session_id: str | None = None
    texts: list[str] = field(default_factory=list)
    error_events: list[dict] = field(default_factory=list)
    unknown_types: list[str] = field(default_factory=list)
    malformed_lines: list[int] = field(default_factory=list)  # 1-based

    @property
    def final_text(self) -> str:
        """Concatenated assistant text parts, in stream order."""
        return "\n".join(self.texts)


def parse_ndjson(data: bytes) -> tuple[ParsedRun, str]:
    """Parse raw stdout bytes. Never raises on malformed lines.

    Returns ``(parsed, encoding_note)``. Raises :class:`ValueError` only
    when the bytes cannot be decoded at all.
    """
    text, encoding_note = decode_output(data)
    parsed = ParsedRun()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parsed.malformed_lines.append(lineno)
            continue
        if not isinstance(event, dict):
            parsed.malformed_lines.append(lineno)
            continue
        parsed.events.append(event)
        event_type = event.get("type")
        if event_type not in KNOWN_EVENT_TYPES:
            parsed.unknown_types.append(str(event_type))
        if event_type == "error":
            parsed.error_events.append(event)
        session_id = event.get("sessionID") or None
        if session_id and parsed.session_id is None:
            parsed.session_id = session_id
        part = event.get("part")
        if isinstance(part, dict) and part.get("type") == "text":
            part_text = part.get("text")
            if isinstance(part_text, str) and part_text:
                parsed.texts.append(part_text)
    return parsed, encoding_note


def classify(parsed: ParsedRun, exit_code: int | None, timed_out: bool) -> tuple[bool, str]:
    """Decide success/failure. Returns ``(ok, message)``.

    Success requires: no timeout, exit 0, no error events, and at least one
    non-empty assistant text part. Everything else fails visibly.
    """
    if timed_out:
        return False, (
            "OpenCode request timed out; its outcome is uncertain — it may "
            "still have reached the model. Do not resend blindly; reconcile "
            "the session first."
        )
    if exit_code is None:
        return False, "OpenCode process could not be started."
    if exit_code != 0:
        detail = ""
        if parsed.error_events:
            first = parsed.error_events[0].get("error", {})
            detail = f" {first.get('message', '')}".rstrip()
        return False, f"OpenCode exited with code {exit_code}.{detail}"
    if parsed.error_events:
        first = parsed.error_events[0].get("error", {})
        return False, f"OpenCode reported an error: {first.get('message', 'unknown')}"
    if parsed.malformed_lines:
        return False, (
            f"OpenCode output had {len(parsed.malformed_lines)} malformed "
            f"line(s); refusing to treat partial output as success."
        )
    if not parsed.texts:
        return False, "OpenCode finished but produced no assistant text."
    return True, "OK"
