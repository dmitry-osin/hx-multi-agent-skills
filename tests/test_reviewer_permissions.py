"""Regression tests for native OpenCode permissions and HX role boundaries."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ("architect", "orchestrator", "developer", "test-engineer", "documentation", "reviewer", "security-auditor")


class NativeAgentPermissionsTests(unittest.TestCase):
    def test_no_agent_overrides_opencode_tool_permissions(self):
        for role in AGENTS:
            with self.subTest(role=role):
                file = ROOT / ".opencode" / "agents" / f"{role}.md"
                text = file.read_text(encoding="utf-8")
                self.assertNotIn("permissions:", text.split("---", 2)[1])
                self.assertIn("mode:", text.split("---", 2)[1])
        self.assertIn("Never edit", (ROOT / ".opencode/agents/reviewer.md").read_text())
        self.assertIn("Never edit", (ROOT / ".opencode/agents/security-auditor.md").read_text())

    def test_review_agents_have_submission_step_budget(self):
        for role in ("reviewer", "security-auditor"):
            with self.subTest(role=role):
                content = (ROOT / ".opencode" / "agents" / f"{role}.md").read_text()
                self.assertIn("steps: 48", content)
                self.assertIn('mode: "FORMAL"', content)
                self.assertIn("hx_submit_review", content)

    def test_upgrade_overwrites_legacy_agent_permission_rules(self):
        with tempfile.TemporaryDirectory(prefix="hx-upgrade-") as directory:
            target = Path(directory) / "config"
            subprocess.run([sys.executable, str(ROOT / "install.py"), "global", "--target", str(target)],
                           check=True, capture_output=True, text=True)
            for role in ("reviewer", "security-auditor", "developer"):
                agent = target / "agents" / f"{role}.md"
                marker = "steps: 48" if role != "developer" else "steps: 24"
                agent.write_text(agent.read_text().replace(
                    marker, 'permissions:\n  - action: shell\n    resource: "*"\n    effect: ask\n' + marker
                ), encoding="utf-8")
                self.assertIn("permissions:", agent.read_text())
            subprocess.run([sys.executable, str(ROOT / "install.py"), "global", "--target", str(target), "--replace-hx"],
                           check=True, capture_output=True, text=True)
            for role in ("reviewer", "security-auditor", "developer"):
                self.assertNotIn("permissions:", (target / "agents" / f"{role}.md").read_text().split("---", 2)[1])


if __name__ == "__main__":
    unittest.main()
