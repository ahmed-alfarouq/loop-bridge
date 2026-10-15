"""OpenCode CLI process integration.

Single responsibility: spawn exactly one ``opencode run`` subprocess,
capture stdout/stderr separately, enforce a timeout. No retries — a timed
out or failed request may already have reached the model.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

DEFAULT_MODEL = "opencode/muse-spark-1.3-contributor-free"
DEFAULT_TIMEOUT_S = 240.0
VERSION_TIMEOUT_S = 15.0

TEST_TITLE_PREFIX = "loopbridge-test-"
TEST_PROMPT = (
    "Reply with exactly this single line: LOOPBRIDGE-PROBE-OK. "
    "Do not use tools, inspect files, modify files, or execute commands."
)


def default_cli_path() -> str:
    """Best-known OpenCode CLI location; overridable via env for tests/portability."""
    override = os.environ.get("LOOPBRIDGE_OPENCODE_CLI")
    if override:
        return override
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    return os.path.join(
        local_app_data, "Programs", "@opencodedesktop", "resources", "opencode-cli.exe"
    )


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    timed_out: bool
    timeout_s: float
    start_error: str | None = None


def check_cli(cli_path: str, timeout_s: float = VERSION_TIMEOUT_S) -> tuple[bool, str]:
    """Read-only availability check. Runs ``cli --version``; no session, no model call."""
    try:
        proc = subprocess.run(
            [cli_path, "--version"], capture_output=True, timeout=timeout_s
        )
    except FileNotFoundError:
        return False, f"not found: {cli_path}"
    except OSError as exc:
        return False, f"cannot start: {exc}"
    except subprocess.TimeoutExpired:
        return False, f"--version timed out after {timeout_s}s"
    if proc.returncode != 0:
        return False, f"--version exited with code {proc.returncode}"
    return True, proc.stdout.decode("utf-8", errors="replace").strip()


def run_test_prompt(
    cli_path: str,
    *,
    model: str = DEFAULT_MODEL,
    title: str,
    prompt: str = TEST_PROMPT,
    work_dir: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> RunResult:
    """Execute exactly one isolated model request.

    Never passes ``--auto``, never attaches files, never retries.
    The caller's ``work_dir`` (an empty temp dir) is the process cwd so the
    agent has no project context.
    """
    cmd = [
        cli_path,
        "run",
        "--standalone",
        "--format", "json",
        "--model", model,
        "--title", title,
        prompt,
    ]
    try:
        proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return RunResult(
            exit_code=None, stdout=b"", stderr=b"",
            timed_out=True, timeout_s=timeout_s,
        )
    except OSError as exc:
        return RunResult(
            exit_code=None, stdout=b"", stderr=b"",
            timed_out=False, timeout_s=timeout_s, start_error=str(exc),
        )
    return RunResult(
        exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr,
        timed_out=False, timeout_s=timeout_s,
    )
