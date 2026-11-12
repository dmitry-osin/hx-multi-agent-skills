"""Regression tests for background Quality Gates and durable result persistence."""

import json
import subprocess
import sys
import tempfile
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HX_HOME = ROOT / ".opencode" / "hx"
sys.path.insert(0, str(HX_HOME))
import gates  # noqa: E402
import state  # noqa: E402


class BackgroundChecksTests(unittest.TestCase):
    def test_worker_persists_standalone_pass_without_server(self):
        with tempfile.TemporaryDirectory(prefix="hx-check-worker-") as temporary:
            cwd = Path(temporary)
            subprocess.run(["git", "init", "-q"], cwd=cwd, check=True)
            (cwd / "README.md").write_text("Test\n")
            subprocess.run(["git", "add", "README.md"], cwd=cwd, check=True)
            subprocess.run(["git", "-c", "user.name=HX", "-c", "user.email=hx@example.org", "commit", "-qm", "initial"], cwd=cwd, check=True)
            config = cwd / ".opencode/hx/quality-gates.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"gates": [{
                "name": "quick", "cwd": ".", "argv": [sys.executable, "-c", "print('PASS')"],
            }]}), encoding="utf-8")
            preview = gates.manifest(cwd, config)
            job_id = str(uuid.uuid4())
            file = state.state_dir(cwd) / "check-jobs" / f"{job_id}.json"
            state.write_json(file, {"job_id": job_id, "cwd": str(cwd),
                                    "manifest_sha256": preview["sha256"], "status": "QUEUED"})
            result = subprocess.run([
                sys.executable, str(HX_HOME / "checks_worker.py"),
                "--job-id", job_id, "--manifest-sha", preview["sha256"],
            ], cwd=cwd, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            stored = json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(stored["status"], "PASS")
            self.assertEqual(stored["result"]["mode"], "STANDALONE")
            self.assertEqual(stored["result"]["manifest_sha256"], preview["sha256"])


if __name__ == "__main__":
    unittest.main()
