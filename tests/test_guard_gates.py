"""Sandbox gate policy must fail closed when isolation is required."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '.opencode/hx'))
import gates  # noqa: E402


class GuardGatesTests(unittest.TestCase):
    def test_required_sandbox_unavailable_returns_failed_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            policy = cwd / '.opencode/hx/guard/policy.json'
            policy.parent.mkdir(parents=True)
            policy.write_text(json.dumps({'mode': 'sandbox-required'}))
            with patch.object(gates.shutil, 'which', return_value=None):
                result = gates.run_gate(cwd, {'name': 'test', 'cwd': str(cwd), 'argv': [sys.executable, '-c', 'print(1)']}, 3)
            self.assertEqual(result['status'], 'FAIL')
            self.assertIn('required', result['error'])

    def test_ask_host_does_not_add_sandbox_without_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            argv = ['echo', 'okay']
            gate = {'name': 'test', 'cwd': str(cwd), 'argv': argv}
            with patch.object(gates.subprocess, 'run') as run:
                run.return_value = type('Result', (), {'returncode': 0, 'stdout': '', 'stderr': ''})()
                self.assertEqual(gates.run_gate(cwd, gate, 3)['status'], 'PASS')
                self.assertEqual(run.call_args.args[0], argv)

    def test_windows_maven_detect_uses_cmd_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            (cwd / "pom.xml").write_text("<project/>")
            with patch.object(gates, "is_windows", return_value=True):
                self.assertEqual(gates.detect(cwd)[0]["argv"],
                                 ["cmd.exe", "/d", "/c", "mvn.cmd", "verify"])

    def test_windows_maven_wrapper_detect_uses_cmd_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            cwd = Path(directory)
            (cwd / "mvnw.cmd").write_text("@echo off\n")
            with patch.object(gates, "is_windows", return_value=True):
                self.assertEqual(gates.detect(cwd)[0]["argv"],
                                 ["cmd.exe", "/d", "/c", "mvnw.cmd", "verify"])


if __name__ == '__main__':
    unittest.main()
