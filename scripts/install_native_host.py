"""Register (or remove) the LoopBridge Firefox native-messaging host.

Per-user setup only: writes HKCU\\Software\\Mozilla\\NativeMessagingHosts,
never HKLM. DRY-RUN BY DEFAULT — prints planned actions; pass --apply to
write, --uninstall to remove the registry key again, --status for a
read-only check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HOST_NAME = "com.loopbridge.bridge"
ADDON_ID = "loopbridge@example.org"
REPO_HOSTS_DIR = Path(__file__).resolve().parent.parent / "hosts"


def _local_app_data() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base)


def install_dir() -> Path:
    return _local_app_data() / "LoopBridge" / "host"


def manifest_path() -> Path:
    return install_dir() / f"{HOST_NAME}.json"


def launcher_path() -> Path:
    return install_dir() / "loopbridge-host.bat"


def build_manifest(python_exe: str) -> dict:
    del python_exe  # launcher .bat resolves the interpreter; kept for API clarity
    return {
        "name": HOST_NAME,
        "description": "LoopBridge native-messaging host (selection inbox)",
        "path": str(launcher_path()),
        "type": "stdio",
        "allowed_extensions": [ADDON_ID],
    }


def build_launcher(host_script: Path) -> str:
    return f'@echo off\r\n"{sys.executable}" -u "{host_script}"\r\n'


def registry_key_path() -> str:
    return rf"Software\Mozilla\NativeMessagingHosts\{HOST_NAME}"


def status() -> dict:
    """Read-only: report whether the host is registered. No changes."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry_key_path()) as key:
            value, _ = winreg.QueryValueEx(key, None)
        return {"registered": True, "manifest": value}
    except FileNotFoundError:
        return {"registered": False, "manifest": None}


def apply(host_script: Path) -> dict:
    """Write launcher + manifest + HKCU key. Explicit opt-in only."""
    import winreg

    target = install_dir()
    target.mkdir(parents=True, exist_ok=True)
    installed_script = target / "loopbridge_host.py"
    installed_script.write_bytes(host_script.read_bytes())
    launcher_path().write_text(build_launcher(installed_script), encoding="utf-8")
    manifest_path().write_text(
        json.dumps(build_manifest(sys.executable), indent=2), encoding="utf-8"
    )
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_key_path()) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(manifest_path()))
    return {"registered": True, "manifest": str(manifest_path())}


def uninstall() -> dict:
    """Remove the HKCU key. Installed files are left for review."""
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_key_path())
        return {"removed": True}
    except FileNotFoundError:
        return {"removed": False, "reason": "key not present"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write files + registry key")
    parser.add_argument("--uninstall", action="store_true", help="remove registry key")
    parser.add_argument("--status", action="store_true", help="read-only check")
    args = parser.parse_args(argv)

    host_script = REPO_HOSTS_DIR / "loopbridge_host.py"
    if args.status or (not args.apply and not args.uninstall):
        print(json.dumps(status(), indent=2))
        if not args.status:
            print("dry-run: manifest would be", manifest_path())
            print("dry-run: launcher would be", launcher_path())
            print("dry-run: registry key would be HKCU\\" + registry_key_path())
            print("re-run with --apply to write.")
        return 0
    if args.uninstall:
        print(json.dumps(uninstall(), indent=2))
        return 0
    if not host_script.exists():
        print(f"host script missing: {host_script}", file=sys.stderr)
        return 2
    print(json.dumps(apply(host_script), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
