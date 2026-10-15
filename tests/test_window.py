"""Minimal window-state test (offscreen; no model calls).

Guards the core safety property: receiving text must never start execution
by itself — both run paths require an explicit button click.
"""
import pytest

pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture()
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("LOOPBRIDGE_INBOX_DIR", str(tmp_path / "inbox"))
    monkeypatch.setenv("LOOPBRIDGE_OPENCODE_CLI", "missing-cli-for-test")
    from PySide6.QtWidgets import QApplication

    from loopbridge.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    yield win
    win.close()


def test_initial_state_runs_nothing(window):
    assert window.windowTitle().startswith("LoopBridge")
    assert window.run_received_button.isEnabled() is False
    assert window.send_button.isEnabled() is False  # nothing completed yet
    assert window.run_button.isEnabled() is True
    assert window._worker is None
    assert window._received_text is None
    assert "unavailable" in window.status_label.text()  # missing-cli-for-test


def test_adopted_text_enables_only_the_explicit_action(window):
    window._adopt_received_text("selected Hamlet quote")
    assert window._received_text == "selected Hamlet quote"
    assert window.inbox_view.toPlainText() == "selected Hamlet quote"
    assert window.run_received_button.isEnabled() is True
    assert window._worker is None  # adopted, not executed
    assert window.response_view.toPlainText() == ""
