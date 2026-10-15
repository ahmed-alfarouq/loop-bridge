"""Tests for the OpenCode subprocess runner (subprocess mocked; no quota)."""
import subprocess

from loopbridge.opencode import runner


def _completed(args, returncode=0, stdout=b"", stderr=b""):
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_builds_isolated_command(monkeypatch, tmp_path):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return _completed(cmd, returncode=0, stdout=b'{"type":"text"}\n')

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.run_test_prompt(
        "opencode-cli", title="t-1", work_dir=str(tmp_path), timeout_s=30.0
    )
    assert result.exit_code == 0 and not result.timed_out and result.start_error is None
    assert seen["cmd"][:6] == [
        "opencode-cli", "run", "--standalone", "--format", "json", "--model",
    ]
    assert "--auto" not in seen["cmd"]
    assert not any(str(a).startswith("-f") and a == "-f" for a in seen["cmd"])
    assert seen["kwargs"]["cwd"] == str(tmp_path)
    assert seen["kwargs"]["timeout"] == 30.0
    assert seen["kwargs"]["capture_output"] is True


def test_timeout_flagged_and_called_once(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.TimeoutExpired(cmd, timeout=30.0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.run_test_prompt(
        "opencode-cli", title="t-2", work_dir=str(tmp_path), timeout_s=30.0
    )
    assert result.timed_out and result.exit_code is None
    assert len(calls) == 1  # no automatic retry


def test_missing_executable_reported(monkeypatch, tmp_path):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = runner.run_test_prompt(
        "missing-cli", title="t-3", work_dir=str(tmp_path)
    )
    assert result.exit_code is None and result.start_error is not None


def test_check_cli_success(monkeypatch):
    monkeypatch.setattr(
        subprocess, "run", lambda cmd, **kw: _completed(cmd, stdout=b"opencode v2.0.29\n")
    )
    ok, detail = runner.check_cli("opencode-cli")
    assert ok and detail == "opencode v2.0.29"


def test_check_cli_missing(monkeypatch):
    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("no such file")

    monkeypatch.setattr(subprocess, "run", fake_run)
    ok, detail = runner.check_cli("missing-cli")
    assert not ok and "not found" in detail


def test_default_cli_path_uses_env_override(monkeypatch):
    monkeypatch.setenv("LOOPBRIDGE_OPENCODE_CLI", "custom-cli")
    assert runner.default_cli_path() == "custom-cli"
