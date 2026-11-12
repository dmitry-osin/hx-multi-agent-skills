"""Adversarial coverage for evidence-bound review reports and completeness."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.opencode' / 'hx'))
import review_contract  # noqa: E402


class ReviewContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        self.git('init', '-q')
        self.git('config', 'user.name', 'HX Test')
        self.git('config', 'user.email', 'hx@example.invalid')
        (self.repo / 'Source.java').write_text(
            'class Source {\n  void maskFirstName() {}\n  int risk = 0;\n  int safe = 1;\n}\n',
            encoding='utf-8',
        )
        self.git('add', 'Source.java')
        self.git('commit', '-qm', 'initial')
        self.sha = self.git('rev-parse', 'HEAD').strip()

    def git(self, *args):
        return subprocess.run(['git', *args], cwd=self.repo, capture_output=True,
                              text=True, check=True).stdout

    def report(self, **changes):
        report = {
            'verdict': 'APPROVED', 'coverage': 'COMPLETE',
            'scope': 'Reviewed the changed code and tests',
            'limitations': [], 'findings': [],
        }
        report.update(changes)
        return report

    def finding(self, **changes):
        item = {
            'id': 'HX-001', 'severity': 'LOW', 'file': 'Source.java',
            'anchor': 'void maskFirstName() {}',
            'evidence': 'Method does not apply masking',
            'recommendation': 'Review the masking implementation',
        }
        item.update(changes)
        return item

    def invalid(self, report, code, *, commit=None):
        with self.assertRaises(review_contract.ReviewValidationError) as caught:
            review_contract.validate(self.repo, report, commit=commit)
        self.assertIn(code, [item['code'] for item in caught.exception.issues])
        self.assertTrue(all(item['path'].startswith('$') for item in caught.exception.issues))

    def test_anchor_resolves_unique_line_without_guessing(self):
        report = self.report(findings=[self.finding()])
        normalized = review_contract.validate(self.repo, report, commit=self.sha)
        self.assertEqual(normalized['findings'][0]['line'], 2)
        self.assertNotIn('line', report['findings'][0])

    def test_wrong_but_in_range_line_is_rejected(self):
        self.invalid(self.report(findings=[self.finding(line=4)]), 'ANCHOR_MISMATCH', commit=self.sha)

    def test_out_of_range_line_is_rejected(self):
        self.invalid(self.report(findings=[self.finding(line=999)]), 'LINE_OUT_OF_RANGE', commit=self.sha)

    def test_made_up_anchor_is_rejected(self):
        self.invalid(self.report(findings=[self.finding(anchor='void inventedMethod() {}')]),
                     'ANCHOR_NOT_FOUND', commit=self.sha)

    def test_ambiguous_anchor_requires_verified_location(self):
        self.invalid(self.report(findings=[self.finding(anchor='int ')]), 'AMBIGUOUS_ANCHOR', commit=self.sha)
        actual = review_contract.validate(self.repo, self.report(findings=[self.finding(anchor='int ', line=3)]))
        self.assertEqual(actual['findings'][0]['line'], 3)

    def test_source_is_bound_to_reviewed_commit_not_dirty_checkout(self):
        (self.repo / 'Source.java').write_text('changed\n', encoding='utf-8')
        report = self.report(findings=[self.finding()])
        self.assertEqual(review_contract.validate(self.repo, report, commit=self.sha)['findings'][0]['line'], 2)
        self.invalid(report, 'ANCHOR_NOT_FOUND')

    def test_new_untracked_worktree_file_is_available_in_formal_review(self):
        new_file = self.repo / 'TraceContextJobDataMapSupport.java'
        new_file.write_text('class TraceContextJobDataMapSupport {\n'
                            '  void captureCurrentContext() {}\n}\n', encoding='utf-8')
        finding = self.finding(file=new_file.name, anchor='void captureCurrentContext() {}')
        report = self.report(verdict='CHANGES_REQUESTED', findings=[finding])
        formal = review_contract.preflight(self.repo, report)
        self.assertTrue(formal['valid'], formal)
        self.assertEqual(formal['report']['findings'][0]['line'], 2)
        standalone_at_base = review_contract.preflight(self.repo, report, commit=self.sha)
        self.assertFalse(standalone_at_base['valid'])
        self.assertEqual(standalone_at_base['issues'][0]['code'], 'FILE_UNAVAILABLE')
        self.assertIn('FORMAL review', standalone_at_base['issues'][0]['message'])

    def test_partial_approved_keeps_verdict_and_coverage_separate(self):
        normalized = review_contract.validate(self.repo, self.report(
            coverage='PARTIAL', limitations=['External model definitions are not available'],
            findings=[self.finding()]))
        self.assertEqual((normalized['verdict'], normalized['coverage']), ('APPROVED', 'PARTIAL'))

    def test_coverage_inconsistencies_are_rejected(self):
        self.invalid(self.report(limitations=['Not inspected fully']), 'COVERAGE_CONFLICT')
        self.invalid(self.report(coverage='PARTIAL'), 'COVERAGE_CONFLICT')
        self.invalid(self.report(coverage='BLOCKED', limitations=['No access to code']), 'VERDICT_CONFLICT')

    def test_high_severity_cannot_be_approved(self):
        self.invalid(self.report(findings=[self.finding(severity='HIGH')]), 'VERDICT_CONFLICT')

    def test_old_schema_and_unknown_properties_return_actionable_paths(self):
        old = self.report()
        old.pop('coverage')
        old['summary'] = 'Not allowed in the schema'
        result = review_contract.preflight(self.repo, old)
        self.assertFalse(result['valid'])
        self.assertTrue(all(item['code'] == 'SCHEMA' for item in result['issues']))
        self.assertTrue(any('coverage' in item['message'] for item in result['issues']))

    def test_path_escapes_and_duplicate_ids_are_rejected(self):
        self.invalid(self.report(findings=[self.finding(file='../outside')]), 'INVALID_PATH')
        self.invalid(self.report(findings=[self.finding(), self.finding()]), 'DUPLICATE_ID')

    def test_preflight_does_not_persist_a_report(self):
        self.assertTrue(review_contract.preflight(self.repo, self.report())['valid'])
        self.assertFalse((self.repo / '.hx').exists())
        self.assertFalse((self.repo / '.git' / 'hx').exists())


if __name__ == '__main__':
    unittest.main()
