"""Run approved Quality Gates independently of OpenCode server lifetime."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import os
import json
import subprocess
import sys

import cli
import runtime
import state


def update(path: Path, **changes: object) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    data.update(changes)
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    state.write_json(path, data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--manifest-sha", required=True)
    args = parser.parse_args()
    cwd = Path.cwd().resolve()
    job_path = state.state_dir(cwd) / "check-jobs" / f"{args.job_id}.json"
    try:
        if not job_path.is_file():
            raise ValueError("Quality Gates job file is missing")
        details = json.loads(job_path.read_text(encoding="utf-8"))
        if details["manifest_sha256"] != args.manifest_sha or Path(details["cwd"]).resolve() != cwd:
            raise ValueError("Quality Gates job context does not match the approved manifest")
        update(job_path, status="RUNNING", pid=os.getpid())
        config = runtime.project_override(cwd, "quality-gates.json")
        result = cli.run_checks(cwd, config, args.manifest_sha, True)
        update(job_path, status=result["status"], result=result)
        return 0 if result["status"] == "PASS" else 2
    except (ValueError, OSError, subprocess.CalledProcessError, RuntimeError) as exc:
        if job_path.is_file():
            update(job_path, status="ERROR", error=str(exc))
        print(f"HX checks worker failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
