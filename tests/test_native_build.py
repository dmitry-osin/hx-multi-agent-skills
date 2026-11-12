"""Verify built-in Plan/Build remains available without shortcut agents."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NativeBuildTests(unittest.TestCase):
    def test_builtin_build_default_and_no_shortcut_files(self):
        config = json.loads((ROOT / "opencode.jsonc").read_text(encoding="utf-8"))
        self.assertEqual(config["default_agent"], "build")
        for folder in ("agents", "commands"):
            for stem in ("hx-quick-fix", "hx-root"):
                self.assertFalse((ROOT / ".opencode" / folder / f"{stem}.md").exists())
        self.assertFalse((ROOT / ".opencode/agents/root.md").exists())
        self.assertTrue((ROOT / ".opencode/commands/hx-plan.md").is_file())
        self.assertTrue((ROOT / ".opencode/commands/hx-approve.md").is_file())

    def test_native_permissions_and_quality_gates_writable_by_policy(self):
        config = json.loads((ROOT / "opencode.jsonc").read_text(encoding="utf-8"))
        self.assertNotIn("policies", config)
        self.assertEqual(
            {(rule["action"], rule["effect"]) for rule in config.get("permissions", [])},
            {("hx_approve", "ask"), ("hx_checks", "ask"), ("hx_land", "ask"), ("hx_land_legacy", "ask")},
        )
        for file in (ROOT / ".opencode/agents").glob("*.md"):
            frontmatter = file.read_text(encoding="utf-8").split("---", 2)[1]
            self.assertNotIn("permissions:", frontmatter, str(file))
        workflow = (ROOT / ".opencode/plugins/hx-command-guard/workflow.js").read_text(encoding="utf-8")
        self.assertIn("save: [preview.sha256]", workflow)
        self.assertIn("startChecks(", workflow)
        self.assertIn("hx_checks_status", workflow)
        self.assertIn("save: []", workflow)
        plugin = (ROOT / ".opencode/plugins/hx-command-guard/index.js").read_text(encoding="utf-8")
        self.assertNotIn("permission.hook", plugin)
        self.assertNotIn("shell.hook", plugin)

    def test_shared_russian_language_policy_applies_to_builtins(self):
        policy = (ROOT / ".opencode/hx/instructions/communication.md").read_text(encoding="utf-8")
        self.assertIn("native Plan and Build", policy)
        self.assertIn("in Russian", policy)
        self.assertIn("in English", policy)
        self.assertIn("actual OpenCode permission", policy)


if __name__ == "__main__":
    unittest.main()
