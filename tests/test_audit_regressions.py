"""Regression coverage of HX v5.1 audit findings."""

import concurrent.futures
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".opencode" / "hx"))
import state  # noqa: E402


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "hx@example.invalid")
        self.git("config", "user.name", "HX")
        (self.repo / "README.md").write_text("hello", encoding="utf-8")
        self.git("add", "README.md")
        self.git("commit", "-qm", "initial")
        shutil.copytree(ROOT / ".opencode", self.repo / ".opencode", ignore=shutil.ignore_patterns("__pycache__", "node_modules"))
        shutil.copy2(ROOT / "opencode.jsonc", self.repo / "opencode.jsonc")
        (self.repo / ".hx").mkdir()
        shutil.copy2(ROOT / ".opencode/hx/templates/plan.example.md", self.repo / ".hx/plan.md")

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def cli(self, *args):
        return subprocess.run([sys.executable, ".opencode/hx/cli.py", *args], cwd=self.repo,
                              check=False, capture_output=True, text=True)

    def test_no_unsafe_command_preamble(self):
        for path in (ROOT / ".opencode/commands").glob("*.md"):
            self.assertNotIn("!`", path.read_text(encoding="utf-8"), str(path))

    def test_approval_refuses_noninteractive_cli_even_with_digest(self):
        self.assertEqual(self.cli("submit").returncode, 0)
        task = state.current(self.repo)[1]
        result = self.cli("approve", "--human-confirm", f"{task['id']}:{task['sha256'][:12]}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("human terminal or HX plugin", result.stdout)
        self.assertEqual(state.current(self.repo)[1]["status"], "DRAFT")

    def test_concurrent_token_writes_do_not_lose_updates(self):
        self.assertEqual(self.cli("submit").returncode, 0)
        def record(_):
            result = self.cli("cost", "--model", "flash", "--input-tokens", "100", "--output-tokens", "10")
            if result.returncode != 0:
                raise AssertionError(result.stdout + result.stderr)
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            list(pool.map(record, range(12)))
        self.assertEqual(len(state.current(self.repo)[1]["cost"]), 12)

    def test_ignored_hx_config_still_changes_revision(self):
        self.assertEqual(self.cli("submit").returncode, 0)
        initial = state.workspace_revision(self.repo)
        exclude = self.repo / ".git/info/exclude"
        exclude.write_text(exclude.read_text() + "\n/.opencode/\n/opencode.jsonc\n")
        policy = self.repo / ".opencode/hx/guard/policy.json"
        policy.write_text(policy.read_text() + " \n")
        self.assertNotEqual(initial, state.workspace_revision(self.repo))

    def test_readonly_yaml_and_json_configs_parse(self):
        config = json.loads((ROOT / "opencode.jsonc").read_text(encoding="utf-8"))
        self.assertTrue(any(p["action"] == "hx_checks" and p["effect"] == "ask" for p in config["permissions"]))
        self.assertEqual(json.loads((ROOT / ".opencode/plugins/hx-command-guard/package.json").read_text())["dependencies"], {})

    def test_tracked_deletion_is_revision_change(self):
        initial = state.workspace_revision(self.repo)
        (self.repo / "README.md").unlink()
        self.assertNotEqual(initial, state.workspace_revision(self.repo))


if __name__ == "__main__":
    unittest.main()
