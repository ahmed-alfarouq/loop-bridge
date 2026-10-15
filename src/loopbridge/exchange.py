"""Request/response association for the Firefox return path.

Pure logic (no Qt, no processes) so routing correctness is unit-testable.
Runs are serialized by the UI (buttons disabled while running), so at most
one run is in flight; completed responses accumulate keyed by request ID and
can never be mixed across tabs.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Request:
    request_id: str
    tab_id: int | None
    text: str


@dataclass
class CompletedRun:
    request_id: str
    tab_id: int | None
    response: str
    session_id: str | None


@dataclass
class ExchangeTracker:
    """Binds each OpenCode run to the request that started it."""

    pending: dict[str, Request] = field(default_factory=dict)
    current_id: str | None = None
    active_id: str | None = None
    completed: dict[str, CompletedRun] = field(default_factory=dict)

    def adopt(self, request: Request) -> None:
        self.pending[request.request_id] = request
        self.current_id = request.request_id

    def begin_run(self) -> str | None:
        """Bind the currently displayed request to the run being started."""
        self.active_id = self.current_id
        return self.active_id

    def finish_run(
        self, response: str, session_id: str | None, ok: bool
    ) -> bool:
        """Record a finished run. Returns False for duplicates/unmatched runs."""
        active = self.active_id
        self.active_id = None
        if active is None or not ok:
            return False  # unmatched completion, or nothing worth delivering
        if active in self.completed:
            return False  # duplicate completion event
        request = self.pending.get(active)
        self.completed[active] = CompletedRun(
            request_id=active,
            tab_id=request.tab_id if request else None,
            response=response,
            session_id=session_id,
        )
        return True

    def sendable(self) -> CompletedRun | None:
        """Completed response for the currently displayed request, if routable."""
        if self.current_id is None:
            return None
        done = self.completed.get(self.current_id)
        if done is None or done.tab_id is None:
            return None
        return done

    def unrun_count(self) -> int:
        return sum(1 for rid in self.pending if rid not in self.completed)
