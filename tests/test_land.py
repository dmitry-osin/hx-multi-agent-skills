"""Git landing must preserve reviewed source and require separate approvals."""

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.opencode' / 'hx'))
import cli  # noqa: E402
import land  # noqa: E402
import state  # noqa: E402


class LandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'repo'
        self.root.mkdir()
        self.run_git(self.root, 'init', '-q')
        self.run_git(self.root, 'config', 'user.name', 'HX Test')
        self.run_git(self.root, 'config', 'user.email', 'hx@example.invalid')
        (self.root / 'README.md').write_text('Base\n')
        self.run_git(self.root, 'add', 'README.md')
        self.run_git(self.root, 'commit', '-qm', 'initial')
        plan = self.root / '.hx/plan.md'
        plan.parent.mkdir()
        plan.write_text((ROOT / '.opencode/hx/templates/plan.example.md').read_text())
        state.register(self.root)
        state.approve(self.root)
        self.worktree = Path(self.temp.name) / 'feature'
        self.run_git(self.root, 'worktree', 'add', '-qb', 'hx-feature', str(self.worktree))
        cli.attach(self.root, self.worktree)
        cli.start(self.worktree)
        (self.worktree / 'README.md').write_text('Completed source\n')
        (self.worktree / 'NewFeature.java').write_text('class NewFeature {}\n')
        self.complete()

    def run_git(self, cwd, *args):
        return subprocess.run(['git', *args], cwd=cwd, capture_output=True,
                              text=True, check=True).stdout.strip()

    def complete(self):
        revision = state.workspace_revision(self.worktree)
        data, task = state.current(self.worktree)
        task.update(status='VERIFYING', checks='PASS', review='APPROVED', security='APPROVED',
                    review_coverage='COMPLETE', security_coverage='COMPLETE',
                    checks_revision=revision, review_revision=revision, security_revision=revision)
        state.save(self.worktree, data)
        self.assertEqual(cli.can_complete(self.worktree)['status'], 'COMPLETED')

    def test_preview_commit_merge_preserves_content_and_history(self):
        initial = self.run_git(self.root, 'rev-parse', 'HEAD')
        preview = land.preview(self.worktree)
        self.assertEqual(preview['proof'], 'VERIFIED')
        self.assertEqual(preview['files'], ['NewFeature.java', 'README.md'])
        self.assertEqual(preview['target_head'], initial)
        self.assertEqual(self.run_git(self.root, 'rev-parse', 'HEAD'), initial)
        committed = land.commit(self.worktree, preview['manifest_sha256'])
        self.assertEqual(committed['phase'], 'COMMITTED')
        self.assertEqual(self.run_git(self.root, 'rev-parse', 'HEAD'), initial)
        self.assertEqual(self.run_git(self.worktree, 'status', '--short'), '')
        merge_plan = land.preview(self.worktree)
        self.assertEqual(merge_plan['phase'], 'MERGE')
        merged = land.merge(self.worktree, merge_plan['manifest_sha256'])
        self.assertEqual(merged['phase'], 'MERGED')
        self.assertEqual((self.root / 'README.md').read_text(), 'Completed source\n')
        self.assertEqual((self.root / 'NewFeature.java').read_text(), 'class NewFeature {}\n')
        self.assertEqual(self.run_git(self.root, 'rev-list', '--count', f'{initial}..HEAD'), '2')
        self.assertEqual(self.run_git(self.root, 'rev-parse', 'HEAD^{tree}'), committed['tree'])
        self.assertTrue(self.worktree.exists())
        self.assertEqual(state.current(self.root)[1]['landing']['status'], 'MERGED')

    def test_stale_preview_and_modified_source_block_commit(self):
        preview = land.preview(self.worktree)
        (self.worktree / 'NewFeature.java').write_text('tampered source\n')
        with self.assertRaisesRegex(ValueError, 'differs from completed'):
            land.commit(self.worktree, preview['manifest_sha256'])
        self.assertEqual(self.run_git(self.worktree, 'rev-parse', 'HEAD'),
                         self.run_git(self.root, 'rev-parse', 'HEAD'))

    def test_advanced_target_branch_blocks_landing(self):
        (self.root / 'new.txt').write_text('unrelated\n')
        self.run_git(self.root, 'add', 'new.txt')
        self.run_git(self.root, 'commit', '-qm', 'advanced')
        with self.assertRaisesRegex(ValueError, 'advanced'):
            land.preview(self.worktree)

    def test_advanced_target_branch_can_prepare_pr_without_merging(self):
        (self.root / 'new.txt').write_text('unrelated\n')
        self.run_git(self.root, 'add', 'new.txt')
        self.run_git(self.root, 'commit', '-qm', 'advanced')
        preview = land.preview(self.worktree, strategy='pr')
        self.assertEqual(preview['strategy'], 'pr')
        result = land.commit(self.worktree, preview['manifest_sha256'], strategy='pr')
        self.assertEqual(result['phase'], 'COMMITTED')
        self.assertEqual(land.preview(self.worktree)['phase'], 'PR_READY')
        self.assertEqual(land.prepare_pr(self.worktree)['phase'], 'PR_PREPARED')
        with self.assertRaisesRegex(ValueError, 'MERGE|preview'):
            land.merge(self.worktree, preview['manifest_sha256'])

    def test_dirty_original_blocks_landing(self):
        (self.root / 'README.md').write_text('other change\n')
        with self.assertRaisesRegex(ValueError, 'dirty'):
            land.preview(self.worktree)

    def test_cleanup_only_from_original_after_merge(self):
        with self.assertRaisesRegex(ValueError, 'Only merged'):
            land.cleanup(self.root)
        previous = land.preview(self.worktree)
        land.commit(self.worktree, previous['manifest_sha256'])
        merge_plan = land.preview(self.worktree)
        land.merge(self.worktree, merge_plan['manifest_sha256'])
        with self.assertRaisesRegex(ValueError, 'original checkout'):
            land.cleanup(self.worktree)
        removed = land.cleanup(self.root)
        self.assertEqual(removed['phase'], 'CLEANED')
        self.assertFalse(self.worktree.exists())
        self.assertEqual(state.current(self.root)[1]['landing']['status'], 'CLEANED')

    def test_pr_preparation_never_merges(self):
        preview = land.preview(self.worktree)
        commit = land.commit(self.worktree, preview['manifest_sha256'])
        drafted = land.prepare_pr(self.worktree)
        self.assertEqual(drafted['phase'], 'PR_PREPARED')
        self.assertIn('NewFeature.java', Path(drafted['path']).read_text())
        self.assertNotEqual(self.run_git(self.root, 'rev-parse', 'HEAD'), commit['commit'])
        self.assertEqual(land.preview(self.worktree)['phase'], 'MERGE')

    def test_pr_draft_refuses_modified_committed_source(self):
        preview = land.preview(self.worktree)
        land.commit(self.worktree, preview['manifest_sha256'])
        (self.worktree / 'README.md').write_text('Changed after commit\n')
        with self.assertRaisesRegex(ValueError, 'changed since commit'):
            land.prepare_pr(self.worktree)

    def test_git_rename_is_included_in_source_commit(self):
        self.run_git(self.worktree, 'mv', 'README.md', 'renamed README.md')
        self.complete_again_after_changes()
        preview = land.preview(self.worktree)
        self.assertIn('README.md', preview['files'])
        self.assertIn('renamed README.md', preview['files'])
        land.commit(self.worktree, preview['manifest_sha256'])
        changed = self.run_git(self.worktree, 'show', '--format=', '--name-status', 'HEAD')
        self.assertIn('renamed README.md', changed)

    def complete_again_after_changes(self):
        data, task = state.current(self.worktree)
        revision = state.workspace_revision(self.worktree)
        task['status'] = 'VERIFYING'
        task.update(checks_revision=revision, review_revision=revision, security_revision=revision)
        state.save(self.worktree, data)
        cli.can_complete(self.worktree)

    def test_staged_hx_managed_files_block_commit(self):
        path = self.worktree / '.opencode/hx/quality-gates.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
        self.run_git(self.worktree, 'add', '-f', str(path.relative_to(self.worktree)))
        with self.assertRaisesRegex(ValueError, 'Staged HX-managed'):
            land.preview(self.worktree)

    def test_local_hx_tooling_is_not_committed(self):
        path = self.worktree / '.opencode/hx/quality-gates.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
        plan = land.preview(self.worktree)
        self.assertNotIn('.opencode/hx/quality-gates.json', plan['files'])
        land.commit(self.worktree, plan['manifest_sha256'])
        self.assertNotIn('.opencode/hx/quality-gates.json',
                         self.run_git(self.worktree, 'show', '--format=', '--name-only', 'HEAD'))

    def test_legacy_completion_requires_same_runtime_revision(self):
        data, task = state.current(self.worktree)
        task.pop('land_source_digest')
        state.save(self.worktree, data)
        self.assertEqual(land.preview(self.worktree)['proof'], 'LEGACY_VERIFIED')
        (self.worktree / '.opencode/hx/cli.py').parent.mkdir(parents=True, exist_ok=True)
        (self.worktree / '.opencode/hx/cli.py').write_text('runtime update\n')
        with self.assertRaisesRegex(ValueError, 'predates land source snapshots'):
            land.preview(self.worktree)
        accepted = land.preview(self.worktree, legacy_override=True)
        self.assertEqual(accepted['proof'], 'LEGACY_MANUAL')
        committed = land.commit(self.worktree, accepted['manifest_sha256'], legacy_override=True)
        self.assertEqual(committed['source_proof'], 'LEGACY_MANUAL')

    def test_no_task_or_incomplete_task_blocks(self):
        data, task = state.current(self.worktree)
        task['status'] = 'BLOCKED'
        state.save(self.worktree, data)
        with self.assertRaisesRegex(ValueError, 'Plan status'):
            land.preview(self.worktree)


if __name__ == '__main__':
    unittest.main()
