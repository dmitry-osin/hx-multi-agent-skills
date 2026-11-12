"""Global and project mode integration tests without an OpenCode server."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import install  # noqa: E402


class InstallModesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.create_repo("project-a")

    def run_git(self, cwd, *args):
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)

    def create_repo(self, name):
        repo = self.base / name
        repo.mkdir()
        self.run_git(repo, "init", "-q")
        self.run_git(repo, "config", "user.name", "HX Test")
        self.run_git(repo, "config", "user.email", "test@example.invalid")
        (repo / "README.md").write_text("ready\n", encoding="utf-8")
        self.run_git(repo, "add", "README.md")
        self.run_git(repo, "commit", "-qm", "init")
        return repo

    def test_global_install_preserves_user_config_and_is_idempotent(self):
        config = self.base / "user" / ".config" / "opencode"
        config.mkdir(parents=True)
        (config / "opencode.jsonc").write_text('''{
            // Keep the user's model and MCP settings.
            "model": "other/model",
            "mcp": {"custom": {"type": "local", "command": ["test"]}},
        }''', encoding="utf-8")
        first = install.install("global", config)
        self.assertGreater(first["files_updated"], 30)
        self.assertTrue((config / "plugins/hx-command-guard/index.js").exists())
        self.assertTrue((config / "hx/review_contract.py").exists())
        settings = install.load_config(config / "opencode.jsonc")
        self.assertEqual(settings["model"], "other/model")
        self.assertIn("custom", settings["mcp"])
        self.assertNotIn("policies", settings)
        communication = (config / "hx/instructions/communication.md").as_posix()
        self.assertIn(communication, settings["instructions"])
        self.assertEqual(settings["instructions"].count(communication), 1)
        self.assertEqual(settings["default_agent"], "build")
        self.assertFalse((config / "commands/hx-quick-fix.md").exists())
        self.assertTrue(first["backup"])
        second = install.install("global", config)
        self.assertEqual(second["files_updated"], 0)
        self.assertFalse(second["config_updated"])
        after = install.load_config(config / "opencode.jsonc")
        self.assertEqual(after["instructions"].count(communication), 1)

    def test_legacy_access_rules_are_removed_but_custom_permissions_remain(self):
        config = self.base / "legacy" / "opencode"
        install.install("global", config)
        path = config / "opencode.jsonc"
        settings = install.load_config(path)
        settings["permissions"] += [
            {"action": "shell", "resource": "*", "effect": "ask"},
            {"action": "external_directory", "resource": "*", "effect": "ask"},
            {"action": "shell", "resource": "git push *", "effect": "deny"},
        ]
        settings["policies"] = [
            {"action": "tool.use", "resource": "edit:.opencode/hx/**", "effect": "deny"},
            {"action": "tool.use", "resource": "edit:.opencode/agents/**", "effect": "deny"},
            {"action": "tool.use", "resource": "edit:opencode.jsonc", "effect": "deny"},
            {"action": "tool.use", "resource": "shell:rm -rf *", "effect": "deny"},
        ]
        path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        dry = install.install("global", config, replace=True, dry_run=True)
        self.assertTrue(dry["config_to_update"])
        updated = install.install("global", config, replace=True)
        migrated = install.load_config(path)
        self.assertNotIn({"action": "shell", "resource": "*", "effect": "ask"}, migrated["permissions"])
        self.assertNotIn({"action": "tool.use", "resource": "edit:.opencode/hx/**", "effect": "deny"}, migrated["policies"])
        self.assertIn({"action": "shell", "resource": "git push *", "effect": "deny"}, migrated["permissions"])
        self.assertIn({"action": "tool.use", "resource": "shell:rm -rf *", "effect": "deny"}, migrated["policies"])
        self.assertTrue((Path(updated["backup"]) / "opencode.jsonc").exists())
        # Native permissions also apply after repeated upgrades.
        install.install("global", config, replace=True)
        self.assertEqual(install.load_config(path), migrated)

    def test_first_install_does_not_remove_user_permission_rules(self):
        config = self.base / "fresh" / "opencode"
        config.mkdir(parents=True)
        path = config / "opencode.jsonc"
        rule = {"action": "shell", "resource": "*", "effect": "ask"}
        path.write_text(json.dumps({"permissions": [rule]}), encoding="utf-8")
        install.install("global", config, replace=True)
        self.assertIn(rule, install.load_config(path)["permissions"])

    def test_local_install_and_collision_protection(self):
        result = install.install("local", self.repo)
        self.assertTrue((self.repo / ".opencode/hx/cli.py").exists())
        self.assertTrue((self.repo / ".opencode/hx/review_contract.py").exists())
        self.assertTrue((self.repo / "opencode.jsonc").exists())
        self.assertEqual(result["mode"], "local")
        project_config = install.load_config(self.repo / "opencode.jsonc")
        self.assertIn(".opencode/hx/instructions/communication.md", project_config["instructions"])
        self.assertFalse((self.repo / ".opencode/agents/hx-quick-fix.md").exists())
        agent = self.repo / ".opencode/agents/architect.md"
        agent.write_text("custom user version", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exists and differs"):
            install.install("local", self.repo)
        self.assertEqual(agent.read_text(encoding="utf-8"), "custom user version")
        replaced = install.install("local", self.repo, replace=True)
        self.assertTrue(replaced["backup"])
        self.assertTrue((Path(replaced["backup"]) / ".opencode/agents/architect.md").exists())
        self.assertIn(".git", replaced["backup"])
        self.assertFalse((self.repo / ".hx-install-backups").exists())

    def test_global_runtime_can_manage_two_repos_without_local_bundle(self):
        global_dir = self.base / "config" / "opencode"
        install.install("global", global_dir)
        second = self.create_repo("project-b")
        for repo in (self.repo, second):
            (repo / ".hx").mkdir()
            shutil.copy2(ROOT / ".opencode/hx/templates/plan.example.md", repo / ".hx/plan.md")
            cli = global_dir / "hx/cli.py"
            process = subprocess.run([sys.executable, str(cli), "submit"], cwd=repo,
                                     capture_output=True, text=True, check=True)
            result = json.loads(process.stdout)
            self.assertEqual(result["status"], "DRAFT")
            self.assertFalse((repo / ".opencode").exists())
            gitpath = self.run_git(repo, "rev-parse", "--git-common-dir").stdout.strip()
            self.assertTrue((repo / gitpath / "hx" / "state.json").exists())
        self.assertNotEqual(
            json.loads((self.repo / ".git/hx/state.json").read_text())["current"],
            json.loads((second / ".git/hx/state.json").read_text())["current"],
        )

    def test_global_runtime_worktree_does_not_copy_bundle(self):
        global_dir = self.base / "global" / "opencode"
        install.install("global", global_dir)
        cli = global_dir / "hx/cli.py"
        (self.repo / ".hx").mkdir()
        shutil.copy2(ROOT / ".opencode/hx/templates/plan.example.md", self.repo / ".hx/plan.md")

        def run(cwd, *args):
            import os
            env = os.environ.copy()
            if args and args[0] == "approve":
                env["HX_PLUGIN_APPROVED"] = "1"  # Simulate explicit OpenCode permission approval.
            proc = subprocess.run([sys.executable, str(cli), *args], cwd=cwd, env=env,
                                  capture_output=True, text=True, check=True)
            return json.loads(proc.stdout)

        task = run(self.repo, "submit")
        run(self.repo, "approve", "--human-confirm", f"{task['id']}:{task['sha256'][:12]}")
        worktree = self.base / "feature-worktree"
        self.run_git(self.repo, "worktree", "add", "-qb", "hx-test", str(worktree))
        run(self.repo, "attach", str(worktree))
        self.assertFalse((worktree / ".opencode").exists())
        self.assertTrue((worktree / ".hx/plan.md").exists())
        self.assertEqual(run(worktree, "start")["status"], "IMPLEMENTING")
        self.assertEqual(run(worktree, "status")["integrity"], "VALID")

    def test_project_dot_opencode_config_is_merged_in_place(self):
        inner = self.repo / ".opencode" / "opencode.jsonc"
        inner.parent.mkdir()
        inner.write_text('{"model": "custom/models", "theme": "dark"}', encoding="utf-8")
        install.install("local", self.repo)
        result = install.load_config(inner)
        self.assertEqual(result["model"], "custom/models")
        self.assertEqual(result["theme"], "dark")
        self.assertNotIn("policies", result)
        self.assertIn(".opencode/hx/instructions/communication.md", result["instructions"])
        self.assertFalse((self.repo / "opencode.jsonc").exists())
        self.assertTrue((self.repo / ".opencode/opencode.jsonc").exists())
        # Local configuration is recognized as HX-managed during plan approval.
        sys.path.insert(0, str(ROOT / ".opencode/hx"))
        import state
        self.assertFalse(state.dirty_project_files(self.repo))

    def test_local_settings_override_without_global_file_copy(self):
        install.install("local", self.repo)
        local = self.repo / ".opencode/hx/budget.json"
        data = json.loads(local.read_text(encoding="utf-8"))
        self.assertGreater(data["soft_limit_usd"], 0)
        self.assertFalse((self.repo / ".hx").exists())

    def test_preserves_other_instruction_files_when_installing(self):
        config = self.base / "opencode"
        config.mkdir()
        (config / "opencode.jsonc").write_text(
            '{"instructions": ["README.md", "docs/guide.md"]}', encoding="utf-8"
        )
        install.install("global", config)
        rules = install.load_config(config / "opencode.jsonc")["instructions"]
        self.assertEqual(rules[:2], ["README.md", "docs/guide.md"])
        self.assertEqual(rules[-1], (config / "hx/instructions/communication.md").as_posix())

    def test_rejects_non_list_instructions_without_modifying_files(self):
        config = self.base / "broken" / "opencode"
        config.mkdir(parents=True)
        original = '{"instructions": "README.md"}'
        (config / "opencode.jsonc").write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Cannot merge instructions"):
            install.install("global", config)
        self.assertEqual((config / "opencode.jsonc").read_text(), original)
        self.assertFalse((config / "agents/hx-quick-fix.md").exists())

    def test_upgrade_removes_retired_agents_and_preserves_custom_root(self):
        config = self.base / "migration" / "opencode"
        install.install("global", config)
        settings_path = config / "opencode.jsonc"
        settings = install.load_config(settings_path)
        settings["default_agent"] = "architect"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")
        old_agent = config / "agents/hx-quick-fix.md"
        old_command = config / "commands/hx-quick-fix.md"
        root_agent = config / "agents/root.md"
        hx_root_command = config / "commands/hx-root.md"
        old_agent.write_text("HX Quick Fix agent", encoding="utf-8")
        old_command.write_text("HX quick-fix command", encoding="utf-8")
        hx_root_command.write_text("HX Root shortcut", encoding="utf-8")
        root_agent.write_text("My personal root agent", encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "Retired HX files"):
            install.install("global", config)
        preview = install.install("global", config, replace=True, dry_run=True)
        self.assertEqual(preview["files_to_remove"], 3)
        self.assertTrue(old_agent.is_file())
        result = install.install("global", config, replace=True)
        self.assertEqual(result["files_removed"], 3)
        self.assertFalse(old_agent.exists())
        self.assertFalse(old_command.exists())
        self.assertFalse(hx_root_command.exists())
        self.assertTrue(root_agent.exists())
        self.assertEqual(install.load_config(settings_path)["default_agent"], "build")
        backup_root = Path(result["backup"])
        self.assertTrue((backup_root / "agents/hx-quick-fix.md").exists())
        self.assertTrue((backup_root / "commands/hx-root.md").exists())

    def test_upgrade_migrates_retired_default_and_agent_config(self):
        global_dir = self.base / "retired" / "opencode"
        install.install("global", global_dir)
        config_path = global_dir / "opencode.jsonc"
        settings = install.load_config(config_path)
        settings["default_agent"] = "hx-root"
        settings["agents"] = {"hx-root": {"mode": "primary"}, "build": {"steps": 10}}
        config_path.write_text(json.dumps(settings), encoding="utf-8")
        (global_dir / "agents/hx-root.md").write_text("# HX Root", encoding="utf-8")
        result = install.install("global", global_dir, replace=True)
        self.assertEqual(result["files_removed"], 1)
        new_settings = install.load_config(config_path)
        self.assertEqual(new_settings["default_agent"], "build")
        self.assertNotIn("hx-root", new_settings["agents"])
        self.assertIn("build", new_settings["agents"])

    def test_upgrade_removes_marked_root_but_not_other_custom_defaults(self):
        install.install("local", self.repo)
        old_root = self.repo / ".opencode/agents/root.md"
        old_root.write_text("# HX Root\nManaged HX role", encoding="utf-8")
        path = self.repo / "opencode.jsonc"
        config = install.load_config(path)
        config["default_agent"] = "plan"
        path.write_text(json.dumps(config), encoding="utf-8")
        result = install.install("local", self.repo, replace=True)
        self.assertEqual(result["files_removed"], 1)
        self.assertFalse(old_root.exists())
        self.assertEqual(install.load_config(path)["default_agent"], "plan")
        self.assertTrue((Path(result["backup"]) / ".opencode/agents/root.md").exists())

    def test_jsonc_parser_does_not_strip_strings(self):
        parsed = json.loads(install.strip_jsonc('''{
          "url": "https://example.test//path", "note": "/* literal */",
          "arr": [1, 2,], /* ignore */
        }'''))
        self.assertEqual(parsed["url"], "https://example.test//path")
        self.assertEqual(parsed["arr"], [1, 2])


if __name__ == "__main__":
    unittest.main()
