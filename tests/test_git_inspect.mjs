import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { inspectGit } from '../.opencode/plugins/hx-command-guard/git-inspect.js';

const run = (cwd, ...args) => execFileSync('git', args, {
  cwd, encoding: 'utf8', timeout: 10000, windowsHide: true,
}).trim();

function withRepo(check) {
  const cwd = mkdtempSync(join(tmpdir(), 'hx-git-test-'));
  try {
    run(cwd, 'init', '-q');
    run(cwd, 'config', 'user.name', 'HX Test');
    run(cwd, 'config', 'user.email', 'hx@example.invalid');
    writeFileSync(join(cwd, 'app.txt'), 'before\n');
    run(cwd, 'add', '.');
    run(cwd, 'commit', '-qm', 'first');
    const base = run(cwd, 'rev-parse', 'HEAD');
    writeFileSync(join(cwd, 'app.txt'), 'after\n');
    run(cwd, 'add', '.');
    run(cwd, 'commit', '-qm', 'second');
    const target = run(cwd, 'rev-parse', 'HEAD');
    check({ cwd, base, target });
  } finally {
    rmSync(cwd, { recursive: true, force: true });
  }
}

test('SHA ancestry references and commit parents work independently from HEAD', () => {
  withRepo(({ cwd, base, target }) => {
    writeFileSync(join(cwd, 'later.txt'), 'later\n');
    run(cwd, 'add', '.');
    run(cwd, 'commit', '-qm', 'third');
    assert.deepEqual(inspectGit(cwd, { action: 'commit', target }).parents, [base]);
    assert.equal(inspectGit(cwd, { action: 'commit', target: `${target}~1` }).sha, base);
    assert.equal(inspectGit(cwd, { action: 'commit', target: `${target}^` }).sha, base);
    assert.notEqual(inspectGit(cwd, { action: 'commit', target: 'HEAD~1' }).sha, base);
    assert.deepEqual(inspectGit(cwd, { action: 'commit', target: base }).parents, []);
  });
});

test('file with base returns diff, while without base returns source', () => {
  withRepo(({ cwd, base, target }) => {
    const patch = inspectGit(cwd, { action: 'file', base, target, path: 'app.txt' });
    assert.equal(patch.contentType, 'diff');
    assert.equal(patch.base, base);
    assert.match(patch.output, /-before/);
    assert.match(patch.output, /\+after/);
    const source = inspectGit(cwd, { action: 'file', target, path: 'app.txt' });
    assert.equal(source.contentType, 'source');
    assert.equal(source.output, 'after\n');
  });
});

test('merge commit provides ordered parents and resolves the second parent', () => {
  withRepo(({ cwd, base, target }) => {
    const main = run(cwd, 'symbolic-ref', '--short', 'HEAD');
    run(cwd, 'checkout', '-qb', 'topic', base);
    writeFileSync(join(cwd, 'branch.txt'), 'topic\n');
    run(cwd, 'add', '.');
    run(cwd, 'commit', '-qm', 'topic');
    const other = run(cwd, 'rev-parse', 'HEAD');
    run(cwd, 'checkout', '-q', main);
    run(cwd, 'merge', '--no-ff', '-qm', 'merge', 'topic');
    const merge = run(cwd, 'rev-parse', 'HEAD');
    assert.deepEqual(inspectGit(cwd, { action: 'commit', target: merge }).parents, [target, other]);
    assert.equal(inspectGit(cwd, { action: 'commit', target: `${merge}^2` }).sha, other);
  });
});

test('unsupported git expressions cannot be forwarded as options or paths', () => {
  withRepo(({ cwd, target }) => {
    for (const value of ['--help', 'HEAD@{1}', 'main;whoami', `${target}~1^2`, `${target}:app.txt`, `${target}~1000`]) {
      assert.throws(() => inspectGit(cwd, { action: 'commit', target: value }), /expected SHA or HEAD/);
    }
    assert.throws(() => inspectGit(cwd, { action: 'file', target, base: '--help', path: 'app.txt' }), /expected SHA or HEAD/);
    assert.throws(() => inspectGit(cwd, { action: 'file', target, base: 'HEAD', path: '../secret' }), /safe relative/);
  });
});
