"""Local acceptance tests for HX v4 state, worktrees and quality gates."""

import json
import hashlib
import hmac
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".opencode" / "hx"))
import cli  # noqa: E402
import gates  # noqa: E402
import state  # noqa: E402


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.email", "hx@example.invalid")
        self.git("config", "user.name", "HX Test")
        (self.repo / "README.md").write_text("Project\n")
        self.git("add", "README.md")
        self.git("commit", "-qm", "init")
        shutil.copytree(ROOT / ".opencode", self.repo / ".opencode")
        shutil.copy2(ROOT / "opencode.jsonc", self.repo / "opencode.jsonc")
        (self.repo / ".hx").mkdir()
        content = (ROOT / ".opencode" / "hx" / "templates" / "plan.example.md").read_text()
        (self.repo / ".hx" / "plan.md").write_text(content)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.repo, check=True, capture_output=True)

    def approved_worktree(self):
        task = state.register(self.repo)
        state.approve(self.repo)
        worktree = Path(self.temp.name) / "hx-worktree"
        self.git("worktree", "add", "-qb", "hx-test", str(worktree))
        cli.attach(self.repo, worktree)
        return worktree, task

    def write_gates(self, worktree, exit_code):
        config = worktree / ".opencode" / "hx" / "quality-gates.json"
        data = {"gates": [{"name": "self-test", "argv": [sys.executable, "-c", f"raise SystemExit({exit_code})"]}]}
        config.write_text(json.dumps(data))

    def report(self, worktree, kind, verdict="APPROVED", findings=None, limitations=None):
        target = worktree / ".hx" / "reports" / f"{kind}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        secret = state.state_dir(worktree) / "attest.key"
        secret.write_bytes(b"test-local-plugin-secret")
        payload = json.dumps({
            "agent": "reviewer" if kind == "review" else "security-auditor",
            "session_id": "subsession-1", "message_id": "msg-1",
            "task_id": state.current(worktree)[1]["id"],
            "workspace_revision": state.workspace_revision(worktree),
            "report": {"verdict": verdict, "coverage": "PARTIAL" if limitations else "COMPLETE", "scope": "Project changes", "limitations": limitations or [], "findings": findings or []},
        }, ensure_ascii=False)
        signature = hmac.new(secret.read_bytes(), payload.encode(), hashlib.sha256).hexdigest()
        target.write_text(json.dumps({"payload": payload, "signature": signature}))
        return cli.review(worktree, kind, target)

    def run_gates(self, worktree):
        config = worktree / ".opencode/hx/quality-gates.json"
        return cli.run_checks(worktree, config, gates.manifest(worktree, config)["sha256"], True)

    def test_refuses_approval_without_plan(self):
        with self.assertRaisesRegex(ValueError, "No active"):
            state.approve(self.repo)

    def test_register_and_approve(self):
        task = state.register(self.repo)
        self.assertEqual(task["status"], "DRAFT")
        approved = state.approve(self.repo)
        self.assertEqual(approved["sha256"], task["sha256"])
        with self.assertRaisesRegex(ValueError, "Only a DRAFT"):
            state.approve(self.repo)

    def test_plan_change_revokes_approval(self):
        state.register(self.repo)
        state.approve(self.repo)
        plan = self.repo / ".hx" / "plan.md"
        plan.write_text(plan.read_text() + "\nImportant modification\n")
        with self.assertRaisesRegex(ValueError, "Local plan has changed"):
            state.verify(self.repo)
        updated = state.register(self.repo)
        self.assertEqual((updated["version"], updated["status"]), (2, "DRAFT"))

    def test_start_requires_approved_worktree(self):
        state.register(self.repo)
        state.approve(self.repo)
        with self.assertRaisesRegex(ValueError, "Create and attach"):
            cli.start(self.repo)
        worktree, _ = self.approved_worktree_after_existing()
        with self.assertRaisesRegex(ValueError, "inside approved"):
            cli.start(self.repo)
        self.assertEqual(cli.start(worktree)["status"], "IMPLEMENTING")

    def approved_worktree_after_existing(self):
        worktree = Path(self.temp.name) / "other-worktree"
        self.git("worktree", "add", "-qb", "hx-other", str(worktree))
        cli.attach(self.repo, worktree)
        return worktree, state.current(self.repo)[1]

    def test_full_completion_and_stale_source_rejection(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        self.write_gates(worktree, 0)
        self.assertEqual(self.run_gates(worktree)["status"], "PASS")
        self.report(worktree, "review")
        self.report(worktree, "security")
        (worktree / "README.md").write_text("Changed after review\n")
        with self.assertRaisesRegex(ValueError, "Source changed"):
            cli.can_complete(worktree)
        self.run_gates(worktree)
        self.report(worktree, "review")
        self.report(worktree, "security")
        self.assertEqual(cli.can_complete(worktree)["status"], "COMPLETED")
        self.assertTrue((worktree / ".hx" / "PR.md").exists() is False)
        self.assertTrue(Path(cli.pr(worktree)["path"]).exists())

    def test_formal_partial_approval_cannot_complete_task(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        self.write_gates(worktree, 0)
        self.assertEqual(self.run_gates(worktree)['status'], 'PASS')
        self.report(worktree, 'review', 'APPROVED', limitations=['External dependencies not available'])
        self.report(worktree, 'security', 'APPROVED')
        with self.assertRaisesRegex(ValueError, 'coverage is not COMPLETE'):
            cli.can_complete(worktree)
        self.report(worktree, 'review', 'APPROVED')
        self.assertEqual(cli.can_complete(worktree)['status'], 'COMPLETED')

    def test_failed_or_missing_quality_gates_block(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        result = self.run_gates(worktree)
        self.assertEqual(result["status"], "UNVERIFIED")
        self.assertEqual(state.current(worktree)[1]["status"], "BLOCKED")
        self.write_gates(worktree, 3)
        self.assertEqual(self.run_gates(worktree)["status"], "FAIL")
        with self.assertRaisesRegex(ValueError, "unapproved gates"):
            cli.can_complete(worktree)

    def test_review_validation_and_correction_limit(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        bad = worktree / "bad-review.json"
        bad.write_text('{"verdict":"APPROVED"}')
        with self.assertRaisesRegex(ValueError, "attested"):
            cli.review(worktree, "review", bad)
        for number in range(2):
            self.report(worktree, "review", "CHANGES_REQUESTED")
            self.assertEqual(cli.next_round(worktree)["round"], number + 1)
        self.report(worktree, "review", "CHANGES_REQUESTED")
        with self.assertRaisesRegex(ValueError, "Correction limit"):
            cli.next_round(worktree)

    def test_git_hx_storage_is_not_project_code(self):
        state.register(self.repo)
        storage = state.state_dir(self.repo)
        self.assertTrue((storage / "state.json").exists())
        self.assertTrue((storage / "plans" / state.current(self.repo)[1]["id"] / "v001.md").exists())
        self.assertIn("/.hx/", (self.repo / ".git" / "info" / "exclude").read_text())

    def test_cost_is_manual_only(self):
        state.register(self.repo)
        self.assertIsNone(cli.cost(self.repo, None, 0, 0)["estimated_usd"])
        result = cli.cost(self.repo, "flash", 1_000_000, 1_000_000)
        self.assertEqual(result["estimated_usd"], 0.75)
        self.assertTrue(result["recorded_tokens_only"])

    def test_approval_rejects_uncommitted_source_files(self):
        state.register(self.repo)
        (self.repo / "README.md").write_text("Uncommitted change\n")
        with self.assertRaisesRegex(ValueError, "uncommitted changes"):
            state.approve(self.repo)

    def test_review_cannot_approve_critical_issue(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        target = worktree / "critical.json"
        target.write_text(json.dumps({
            "verdict": "APPROVED",
            "findings": [{"id": "SEC-1", "severity": "CRITICAL", "file": "README.md",
                          "line": 1, "anchor": "Project", "evidence": "Test evidence", "recommendation": "Fix"}],
        }))
        with self.assertRaisesRegex(ValueError, "attested"):
            cli.review(worktree, "security", target)
        with self.assertRaisesRegex(ValueError, "Cannot APPROVE"):
            self.report(worktree, "security", "APPROVED", findings=[{
                "id": "SEC-1", "severity": "CRITICAL", "file": "README.md", "line": 1, "anchor": "Project",
                "evidence": "Test evidence", "recommendation": "Fix it"}])

    def test_budget_soft_cap_blocks_start(self):
        worktree, _ = self.approved_worktree()
        cfg = worktree / ".opencode/hx/budget.json"
        cfg.write_text(json.dumps({"soft_limit_usd": 0.20}))
        cli.cost(worktree, "flash", 1_000_000, 0)
        cli.cost(worktree, "flash", 1_000_000, 0)
        with self.assertRaisesRegex(ValueError, "soft budget"):
            cli.start(worktree)

    def test_detect_without_any_build_files(self):
        self.assertEqual(gates.detect(self.repo), [])
        self.assertEqual(gates.execute(self.repo, self.repo / "unknown.json")["status"], "UNVERIFIED")

    def test_non_ascii_titles_have_distinct_task_ids(self):
        first = self.repo / ".hx/plan.md"
        content = first.read_text()
        first.write_text(content.replace("# Example implementation task", "# 認証を追加"))
        task_a = state.register(self.repo)
        first.write_text(content.replace("# Example implementation task", "# ログインを修正"))
        task_b = state.register(self.repo)
        self.assertNotEqual(task_a["id"], task_b["id"])
        self.assertIn(task_a["id"], state.load(self.repo)["tasks"])
        self.assertIn(task_b["id"], state.load(self.repo)["tasks"])

    def test_revision_catches_commits_and_hx_configuration(self):
        original = state.workspace_revision(self.repo)
        cfg = self.repo / ".opencode/hx/guard/policy.json"
        cfg.write_text(cfg.read_text() + " ")
        changed = state.workspace_revision(self.repo)
        self.assertNotEqual(original, changed)
        cfg.write_text(cfg.read_text().rstrip())
        (self.repo / "README.md").write_text("A commit changes HEAD")
        self.git("add", "README.md")
        self.git("commit", "-qm", "new")
        self.assertNotEqual(original, state.workspace_revision(self.repo))

    def test_manifest_mismatch_never_executes_build(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        self.write_gates(worktree, 0)
        config = worktree / ".opencode/hx/quality-gates.json"
        digest = gates.manifest(worktree, config)["sha256"]
        config.write_text(config.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "manifest"):
            cli.run_checks(worktree, config, digest, True)
        with self.assertRaisesRegex(ValueError, "explicit permission"):
            cli.run_checks(worktree, config, gates.manifest(worktree, config)["sha256"], False)

    def test_review_forgery_and_invalid_schema_fail_closed(self):
        worktree, _ = self.approved_worktree()
        cli.start(worktree)
        target = worktree / "bad.json"
        target.write_text(json.dumps({"payload": "{}", "signature": "abc"}))
        with self.assertRaisesRegex(ValueError, "attestation"):
            cli.review(worktree, "review", target)
        with self.assertRaisesRegex(ValueError, "Invalid review report"):
            self.report(worktree, "review", findings=[{
                "id": "R1", "severity": "LOW", "file": "README.md", "line": "one",
                "evidence": "valid details", "recommendation": "fix it"}])

    def test_worktree_has_no_untracked_hx_bundle(self):
        worktree, _ = self.approved_worktree()
        status = subprocess.check_output(["git", "status", "--short"], cwd=worktree, text=True)
        self.assertNotIn("?? .opencode", status)
        self.assertNotIn("?? opencode.jsonc", status)

    def test_git_status_rename_with_spaces_and_unicode(self):
        filename = "測試 file.txt"
        (self.repo / filename).write_text("content")
        self.git("add", filename)
        self.git("commit", "-qm", "add file")
        self.git("mv", filename, "renamed 測試 file.txt")
        names = state.dirty_project_files(self.repo)
        self.assertTrue(any("renamed" in name for name in names), names)
        self.assertTrue(any("測試" in name for name in names), names)


class ConfigTests(unittest.TestCase):
    def test_json_config_and_required_command_names(self):
        cfg = json.loads((ROOT / "opencode.jsonc").read_text())
        self.assertEqual(cfg["default_agent"], "build")
        self.assertEqual(cfg["worktree"]["directory"], "../hx-worktrees")
        names = {path.stem for path in (ROOT / ".opencode/commands").glob("*.md")}
        self.assertEqual(names, {"hx-plan", "hx-approve", "hx-review", "hx-fix",
                                 "hx-status", "hx-resume", "hx-tests", "hx-audit",
                                 "hx-diff", "hx-pr", "hx-land", "hx-cost", "hx-security-log", "hx-security-status"})

    def test_yaml_frontmatter(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML optional for config validation")
        root = ROOT / ".opencode"
        paths = list(root.glob("commands/*.md")) + list(root.glob("agents/*.md"))
        paths += list(root.glob("skills/*/SKILL.md"))
        self.assertEqual(len(paths), 26)
        for path in paths:
            frontmatter = yaml.safe_load(path.read_text().split("---", 2)[1])
            self.assertTrue(frontmatter, str(path))

    def test_agent_roles_and_models(self):
        roles = {p.stem: p.read_text() for p in (ROOT / ".opencode/agents").glob("*.md")}
        self.assertEqual(len(roles), 7)
        for name in ("architect", "orchestrator", "reviewer", "security-auditor"):
            self.assertIn("deepseek/deepseek-v4-pro", roles[name])
        for name in ("developer", "test-engineer", "documentation"):
            self.assertIn("deepseek/deepseek-flash", roles[name])


if __name__ == "__main__":
    unittest.main()

