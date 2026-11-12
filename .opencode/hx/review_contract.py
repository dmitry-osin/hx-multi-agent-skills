"""Single authoritative validation contract for standalone and formal HX reviews."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from pathlib import Path, PurePosixPath, PureWindowsPath

from process_utils import run
import runtime


class ReviewValidationError(ValueError):
    def __init__(self, issues: list[dict]):
        self.issues = issues
        detail = '; '.join(f"{issue['path']}: {issue['message']}" for issue in issues[:5])
        super().__init__(f"Invalid review report ({len(issues)} issue(s)): {detail}")


def schema() -> dict:
    return json.loads((runtime.HX_HOME / 'review-schema.json').read_text(encoding='utf-8'))


def example() -> dict:
    return {
        'verdict': 'APPROVED',
        'coverage': 'COMPLETE',
        'scope': 'Reviewed the changed files and relevant tests',
        'limitations': [],
        'findings': [],
    }


def issue(code: str, path: str, message: str) -> dict:
    return {'code': code, 'path': path, 'message': message}


def _relative_path(value: str) -> Path | None:
    if not isinstance(value, str) or not value.strip() or '\\' in value:
        return None
    unix, windows = PurePosixPath(value), PureWindowsPath(value)
    if unix.is_absolute() or windows.is_absolute() or windows.drive:
        return None
    if any(part in ('..', '.', '.git') for part in unix.parts):
        return None
    return Path(*unix.parts)


def _source_lines(cwd: Path, relative: Path, commit: str | None) -> list[str]:
    if commit:
        try:
            result = run(
                ['git', '--no-pager', 'show', f'{commit}:{relative.as_posix()}'],
                cwd=cwd, capture_output=True, check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ValueError(
                f'{relative.as_posix()} is not present at Git revision {commit[:12]}. '
                'If the file was added in the approved worktree, use FORMAL review '
                'without target/base. For a standalone range, anchor findings at '
                'the target commit rather than its parent/base.'
            ) from exc
        content = result.stdout
    else:
        root = cwd.resolve()
        absolute = (cwd / relative).resolve()
        if not absolute.is_relative_to(root) or not absolute.is_file():
            raise ValueError('File is missing or outside the workspace')
        content = absolute.read_bytes()
    if len(content) > 16 * 1024 * 1024:
        raise ValueError('Source file exceeds 16 MiB location-verification limit')
    return content.decode('utf-8', errors='replace').splitlines()


def validate(cwd: Path, raw_report: object, *, commit: str | None = None) -> dict:
    """Validate schema, semantic consistency and source-bound evidence anchors.

    Every finding must contain an exact single-line source anchor. If a line is
    supplied, that line must contain the anchor. Otherwise the anchor must occur
    on exactly one line; the resolved line is included in the normalized report.
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ValueError('Install jsonschema==4.26.0 from hx/requirements.txt') from exc

    issues = []
    errors = sorted(Draft202012Validator(schema()).iter_errors(raw_report),
                    key=lambda item: (tuple(str(p) for p in item.absolute_path), item.message))
    for error in errors:
        path = '$' + ''.join(f'[{part}]' if isinstance(part, int) else f'.{part}' for part in error.absolute_path)
        issues.append(issue('SCHEMA', path, error.message))
    if issues:
        raise ReviewValidationError(issues)

    report = deepcopy(raw_report)
    coverage, limitations, verdict = (report[key] for key in ('coverage', 'limitations', 'verdict'))
    if coverage == 'COMPLETE' and limitations:
        issues.append(issue('COVERAGE_CONFLICT', '$.limitations', 'COMPLETE coverage requires no limitations'))
    if coverage in ('PARTIAL', 'BLOCKED') and not limitations:
        issues.append(issue('COVERAGE_CONFLICT', '$.limitations', f'{coverage} coverage requires at least one limitation'))
    if coverage == 'BLOCKED' and verdict == 'APPROVED':
        issues.append(issue('VERDICT_CONFLICT', '$.verdict', 'BLOCKED coverage cannot be APPROVED'))
    if verdict == 'APPROVED' and any(f['severity'] in ('CRITICAL', 'HIGH', 'MEDIUM') for f in report['findings']):
        issues.append(issue('VERDICT_CONFLICT', '$.verdict', 'Cannot APPROVE with CRITICAL/HIGH/MEDIUM findings'))

    ids = [finding['id'] for finding in report['findings']]
    if len(ids) != len(set(ids)):
        issues.append(issue('DUPLICATE_ID', '$.findings', 'Finding IDs must be unique'))

    for index, finding in enumerate(report['findings']):
        prefix = f'$.findings[{index}]'
        relative = _relative_path(finding['file'])
        if relative is None:
            issues.append(issue('INVALID_PATH', f'{prefix}.file', 'Use a safe relative POSIX path without .git, .. or backslashes'))
            continue
        try:
            lines = _source_lines(cwd, relative, commit)
        except (ValueError, OSError, subprocess.CalledProcessError) as exc:
            issues.append(issue('FILE_UNAVAILABLE', f'{prefix}.file', f'Cannot read file at reviewed revision: {exc}'))
            continue

        anchor = finding['anchor']
        if '\n' in anchor or '\r' in anchor or not anchor.strip():
            issues.append(issue('INVALID_ANCHOR', f'{prefix}.anchor', 'Anchor must be a nonblank exact substring of one source line'))
            continue
        line = finding.get('line')
        if line is not None:
            if line > len(lines):
                issues.append(issue('LINE_OUT_OF_RANGE', f'{prefix}.line', f'Line {line} exceeds file length {len(lines)}'))
            elif anchor not in lines[line - 1]:
                issues.append(issue('ANCHOR_MISMATCH', f'{prefix}.anchor',
                                    f'Anchor is not present at {relative.as_posix()}:{line}; read the source instead of guessing a line'))
            continue
        matches = [number for number, content in enumerate(lines, start=1) if anchor in content]
        if len(matches) == 1:
            finding['line'] = matches[0]
        elif not matches:
            issues.append(issue('ANCHOR_NOT_FOUND', f'{prefix}.anchor', 'Exact source anchor was not found at the reviewed revision'))
        else:
            issues.append(issue('AMBIGUOUS_ANCHOR', f'{prefix}.anchor',
                                f'Anchor matches {len(matches)} lines; provide a verified line or more specific anchor'))

    if issues:
        raise ReviewValidationError(issues)
    return report


def preflight(cwd: Path, report: object, *, commit: str | None = None) -> dict:
    try:
        normalized = validate(cwd, report, commit=commit)
        return {'valid': True, 'report': normalized, 'issues': []}
    except ReviewValidationError as exc:
        return {'valid': False, 'issues': exc.issues}
