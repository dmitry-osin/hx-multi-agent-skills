"""Read-only HX plugin telemetry and optional Quality Gate isolation diagnostics."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def state_dir(cwd: Path) -> Path:
    command = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=cwd, text=True, capture_output=True, check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if command.returncode:
        return cwd / ".hx" / "security"
    root = Path(command.stdout.strip())
    return (root if root.is_absolute() else cwd / root).resolve() / "hx" / "security"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def status(cwd: Path) -> dict:
    path = state_dir(cwd)
    local_policy = cwd / ".opencode" / "hx" / "guard" / "policy.json"
    installation_policy = Path(__file__).resolve().parent / "policy.json"
    policy = read_json(local_policy if local_policy.is_file() else installation_policy)
    loaded = read_json(path / "status.json")
    return {
        "permission_mode": "native-opencode",
        "quality_gate_sandbox_policy": policy,
        "last_plugin_load": loaded or None,
        "log_exists": (path / "guard.jsonl").is_file(),
        "log_path": str(path / "guard.jsonl"),
        "warning": "HX does not override native tool permissions. Tool log entries do not confirm approval or denial.",
    }


def log(cwd: Path, limit: int = 30) -> dict:
    path = state_dir(cwd) / "guard.jsonl"
    if not path.is_file():
        return {"records": [], "warning": "No HX Guard events have been recorded"}
    lines = path.read_text(encoding="utf-8").splitlines()
    return {"records": [json.loads(line) for line in lines[-limit:]],
            "warning": "Tool events are diagnostics, not an OpenCode permission-decision audit."}


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command not in ("status", "log"):
        print(json.dumps({"error": "Use status or log"}))
        return 2
    result = status(Path.cwd()) if command == "status" else log(Path.cwd())
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
