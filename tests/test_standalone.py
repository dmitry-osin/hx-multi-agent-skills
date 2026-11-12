"""Regression coverage for independent HX workflows without a formal plan."""

import hashlib
import hmac
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".opencode" / "hx"))
import cli  # noqa: E402
import standalone  # noqa: E402
import state  # noqa: E402


class IndependentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'HX Tester')
        self.git('config', 'user.email', 'hx@example.invalid')
        (self.repo / 'README.md').write_text('Before\nSecond\n', encoding='utf-8')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'initial')
        self.base = self.git('rev-parse', 'HEAD').strip()
        (self.repo / 'README.md').write_text('After\nSecond\n', encoding='utf-8')
        self.git('add', 'README.md')
        self.git('commit', '-qm', 'change')
        self.target = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, check=True,
                              capture_output=True, text=True).stdout

    def signed(self, kind, target, base=None, findings=None):
        state_dir = state.state_dir(self.repo)
        state_dir.mkdir(parents=True, exist_ok=True)
        secret = state_dir / 'attest.key'
        secret.write_bytes(b'hx-test-secret')
        target_kind, sha = standalone.target_revision(self.repo, target, base)
        payload = json.dumps({
            'agent': 'reviewer' if kind == 'review' else 'security-auditor',
            'session_id': f'{kind}-session', 'message_id': 'msg-1',
            'target_kind': target_kind, 'target_sha256': sha,
            'report': {'verdict': 'CHANGES_REQUESTED' if findings else 'APPROVED',
                       'coverage': 'COMPLETE', 'scope': 'Commit changes', 'limitations': [], 'findings': findings or []},
        })
        signature = hmac.new(secret.read_bytes(), payload.encode(), hashlib.sha256).hexdigest()
        file = state_dir / f'{kind}.signed.json'
        file.write_text(json.dumps({'payload': payload, 'signature': signature}), encoding='utf-8')
        return file

    def test_commit_review_without_plan(self):
        self.assertEqual(cli.current_status(self.repo)['status'], 'NO_TASK')
        result = cli.diff(self.repo, self.target)
        self.assertEqual(result['mode'], 'STANDALONE')
        self.assertIn('After', result['patch'])
        report = self.signed('review', self.target, findings=[{
            'id': 'HX-001', 'severity': 'MEDIUM', 'file': 'README.md', 'line': 1, 'anchor': 'After',
            'evidence': 'Content changed without a linked test',
            'recommendation': 'Add an appropriate test',
        }])
        reviewed = standalone.record(self.repo, report, 'review', self.target)
        self.assertEqual(reviewed['verdict'], 'CHANGES_REQUESTED')
        self.assertTrue(Path(reviewed['saved_to']).is_file())
        self.assertFalse((self.repo / '.hx').exists())

    def test_range_without_plan(self):
        report = self.signed('security', self.target, base=self.base)
        saved = standalone.record(self.repo, report, 'security', self.target, self.base)
        self.assertEqual(saved['kind'], 'security')
        self.assertTrue(Path(saved['saved_to']).exists())
        self.assertEqual(cli.current_status(self.repo)['status'], 'NO_TASK')

    def test_draft_plan_does_not_block_commit_review(self):
        (self.repo / '.hx').mkdir()
        (self.repo / '.hx' / 'plan.md').write_text(
            (ROOT / '.opencode/hx/templates/plan.example.md').read_text(encoding='utf-8'),
            encoding='utf-8')
        state.register(self.repo)
        self.assertEqual(cli.current_status(self.repo)['status'], 'DRAFT')
        self.assertEqual(cli.pr(self.repo)['mode'], 'STANDALONE')
        report = self.signed('review', self.target)
        saved = standalone.record(self.repo, report, 'review', self.target)
        self.assertEqual(saved['mode'], 'STANDALONE')
        self.assertEqual(cli.current_status(self.repo)['status'], 'DRAFT')

    def test_preflight_reports_dirty_checkout_before_permission(self):
        (self.repo / '.hx').mkdir()
        (self.repo / '.hx' / 'plan.md').write_text(
            (ROOT / '.opencode/hx/templates/plan.example.md').read_text(encoding='utf-8'),
            encoding='utf-8')
        state.register(self.repo)
        (self.repo / 'new-file.txt').write_text('untracked', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'uncommitted changes'):
            state.preflight_approval(self.repo)

    def test_rejects_incorrect_commit_binding(self):
        report = self.signed('review', self.target)
        with self.assertRaisesRegex(ValueError, 'target changed'):
            standalone.record(self.repo, report, 'review', self.base)


if __name__ == '__main__':
    unittest.main()
