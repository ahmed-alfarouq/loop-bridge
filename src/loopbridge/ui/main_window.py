"""Minimal LoopBridge desktop window (PySide6)."""
from __future__ import annotations

import tempfile
import uuid

from PySide6.QtCore import QFileSystemWatcher, QThread, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from loopbridge import __version__, inbox as inbox_store
from loopbridge import exchange as exchange_store
from loopbridge import outbox as outbox_store
from loopbridge.opencode import events as opencode_events
from loopbridge.opencode import runner as opencode_runner


class _RunWorker(QThread):
    """Runs one OpenCode request off the UI thread. No retries by design."""

    done = Signal(object)

    def __init__(self, cli_path: str, work_dir: str, title: str, prompt: str, parent=None):
        super().__init__(parent)
        self._cli_path = cli_path
        self._work_dir = work_dir
        self._title = title
        self._prompt = prompt

    def run(self) -> None:
        result = opencode_runner.run_test_prompt(
            self._cli_path,
            title=self._title,
            prompt=self._prompt,
            work_dir=self._work_dir,
        )
        self.done.emit({"result": result, "work_dir": self._work_dir})


class MainWindow(QMainWindow):
    def __init__(self, cli_path: str | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"LoopBridge {__version__}")
        self._cli_path = cli_path or opencode_runner.default_cli_path()
        self._worker: _RunWorker | None = None
        self._received_text: str | None = None
        self._seen_inbox: set[str] = set()
        self._exchanges = exchange_store.ExchangeTracker()

        central = QWidget(self)
        layout = QVBoxLayout(central)

        self.status_label = QLabel("OpenCode: checking…", self)
        layout.addWidget(self.status_label)

        self.inbox_label = QLabel("Received from Firefox: (nothing yet)", self)
        layout.addWidget(self.inbox_label)

        self.inbox_view = QTextEdit(self)
        self.inbox_view.setReadOnly(True)
        self.inbox_view.setPlaceholderText("Selected text sent from Firefox appears here.")
        layout.addWidget(self.inbox_view)

        self.run_received_button = QPushButton("Run in OpenCode", self)
        self.run_received_button.setEnabled(False)
        self.run_received_button.clicked.connect(self._on_run_received_clicked)
        layout.addWidget(self.run_received_button)

        self.response_view = QTextEdit(self)
        self.response_view.setReadOnly(True)
        self.response_view.setPlaceholderText("Latest OpenCode response appears here.")
        layout.addWidget(self.response_view)

        self.meta_label = QLabel("", self)
        layout.addWidget(self.meta_label)

        self.send_button = QPushButton("Send result to Firefox", self)
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._on_send_clicked)
        layout.addWidget(self.send_button)

        self.run_button = QPushButton("Run test prompt", self)
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        self.message_label = QLabel("", self)
        layout.addWidget(self.message_label)

        self.setCentralWidget(central)
        self.resize(640, 640)
        self._refresh_cli_status()

        self._inbox_dir = inbox_store.ensure_inbox()
        self._watcher = QFileSystemWatcher([str(self._inbox_dir)], self)
        self._watcher.directoryChanged.connect(self._on_inbox_changed)
        self._adopt_new_inbox_files(initial=True)

    # -- status -----------------------------------------------------------
    def _set_message(self, text: str, is_error: bool) -> None:
        self.message_label.setText(text)
        color = "red" if is_error else "green"
        self.message_label.setStyleSheet(f"color: {color};")

    def _refresh_cli_status(self) -> None:
        ok, detail = opencode_runner.check_cli(self._cli_path)
        if ok:
            self.status_label.setText(f"OpenCode: connected ({detail})")
            self.status_label.setStyleSheet("color: green;")
        else:
            self.status_label.setText(f"OpenCode: unavailable — {detail}")
            self.status_label.setStyleSheet("color: red;")

    # -- inbox ------------------------------------------------------------
    def _adopt_new_inbox_files(self, initial: bool = False) -> None:
        for path in inbox_store.scan(self._inbox_dir):
            if path.name in self._seen_inbox:
                continue
            self._seen_inbox.add(path.name)
            ok, payload = inbox_store.load_request(path)
            inbox_store.mark_done(path)  # exactly-once per client run
            if not ok:
                assert isinstance(payload, str)
                if not initial:
                    self._set_message(f"Ignored invalid selection: {payload}", is_error=True)
                continue
            self._exchanges.adopt(
                exchange_store.Request(
                    request_id=payload.request_id or f"local-{path.name}",
                    tab_id=payload.tab_id,
                    text=payload.text,
                )
            )
            self._adopt_received_text(payload.text)

    def _on_inbox_changed(self, _path: str) -> None:
        self._adopt_new_inbox_files()

    def _adopt_received_text(self, text: str) -> None:
        self._received_text = text
        self.inbox_view.setPlainText(text)
        pending = self._exchanges.unrun_count()
        extra = f", {pending} unrun" if pending > 1 else ""
        self.inbox_label.setText(f"Received from Firefox: ({len(text)} chars{extra})")
        self.run_received_button.setEnabled(True)
        self._refresh_send_button()

    # -- OpenCode execution (explicit user action only) -------------------
    def _start_run(self, title: str, prompt: str, bind_request: bool) -> None:
        self.run_button.setEnabled(False)
        self.run_received_button.setEnabled(False)
        self.send_button.setEnabled(False)
        if bind_request:
            self._exchanges.begin_run()
        else:
            self._exchanges.active_id = None
        self._set_message("Running…", is_error=False)
        self.response_view.clear()
        self.meta_label.setText("")
        work_dir = tempfile.mkdtemp(prefix="loopbridge-")
        self._worker = _RunWorker(self._cli_path, work_dir, title, prompt, self)
        self._worker.done.connect(self._on_run_done)
        self._worker.start()

    def _on_run_clicked(self) -> None:
        title = f"{opencode_runner.TEST_TITLE_PREFIX}{uuid.uuid4().hex[:8]}"
        self._start_run(title, opencode_runner.TEST_PROMPT, bind_request=False)

    def _on_run_received_clicked(self) -> None:
        if self._received_text is None:
            return
        title = f"loopbridge-firefox-{uuid.uuid4().hex[:8]}"
        self._start_run(title, self._received_text, bind_request=True)

    def _on_run_done(self, payload: object) -> None:
        self.run_button.setEnabled(True)
        if self._received_text is not None:
            self.run_received_button.setEnabled(True)
        assert isinstance(payload, dict)
        result = payload["result"]
        if result.start_error is not None:
            self._set_message(f"Could not start OpenCode: {result.start_error}", is_error=True)
            self._refresh_send_button()
            return
        try:
            parsed, _encoding = opencode_events.parse_ndjson(result.stdout)
        except ValueError:
            self.meta_label.setText(f"session: n/a · exit: {result.exit_code}")
            self._set_message("OpenCode output was not decodable; refusing to guess.", is_error=True)
            self._exchanges.finish_run("", None, ok=False)
            self._refresh_send_button()
            return
        ok, message = opencode_events.classify(parsed, result.exit_code, result.timed_out)
        session = parsed.session_id or "n/a"
        self.meta_label.setText(f"session: {session} · exit: {result.exit_code}")
        self._exchanges.finish_run(
            parsed.final_text if ok else "", parsed.session_id, ok=ok
        )
        self._refresh_send_button()
        if not ok:
            stderr_hint = result.stderr.decode("utf-8", errors="replace").strip()
            if stderr_hint and "exit" in message:
                message = f"{message} stderr: {stderr_hint[:300]}"
            self._set_message(message, is_error=True)
            return
        self.response_view.setPlainText(parsed.final_text)
        self._set_message(message, is_error=False)

    # -- return path (explicit user action only) --------------------------
    def _refresh_send_button(self) -> None:
        sendable = self._exchanges.sendable()
        self.send_button.setEnabled(sendable is not None)

    def _on_send_clicked(self) -> None:
        sendable = self._exchanges.sendable()
        if sendable is None or sendable.tab_id is None:
            return  # unroutable (unknown tab): nothing to queue
        try:
            outbox_store.write_response(
                sendable.request_id,
                sendable.tab_id,
                sendable.response,
                session_id=sendable.session_id,
            )
        except ValueError as exc:
            self._set_message(f"Cannot queue result for Firefox: {exc}", is_error=True)
            return
        self._set_message(
            "Result queued — open the LoopBridge popup in the originating "
            "Firefox tab and Fetch it.",
            is_error=False,
        )
