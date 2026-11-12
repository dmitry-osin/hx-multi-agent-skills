import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const source = resolve(import.meta.dirname, '..');
const run = (cwd, args) => execFileSync('git', args, { cwd, encoding: 'utf8', timeout: 10000 }).trim();
const context = agent => ({ agent, sessionID: `${agent}-ses`, messageID: `${agent}-msg`, id: `${agent}-tool` });

async function environment() {
  const temp = mkdtempSync(join(tmpdir(), 'hx-standalone-tool-'));
  const cwd = join(temp, 'repo');
  mkdirSync(cwd);
  run(cwd, ['init', '-q']);
  run(cwd, ['config', 'user.name', 'HX Tester']);
  run(cwd, ['config', 'user.email', 'hx@example.invalid']);
  writeFileSync(join(cwd, 'app.txt'), 'before\n');
  run(cwd, ['add', '.']);
  run(cwd, ['commit', '-qm', 'base']);
  const base = run(cwd, ['rev-parse', 'HEAD']);
  writeFileSync(join(cwd, 'app.txt'), 'after\n');
  run(cwd, ['add', '.']);
  run(cwd, ['commit', '-qm', 'change']);
  const sha = run(cwd, ['rev-parse', 'HEAD']);
  const callbacks = new Map();
  const approvals = [];
  const ctx = {
    location: { directory: cwd },
    permission: { hook: async () => {}, assert: async value => { approvals.push(value); } },
    shell: { hook: async () => {} },
    tool: {
      hook: async () => {},
      transform: async fn => fn({ add: item => callbacks.set(item.name, item) }),
    },
  };
  const plugin = await import(pathToFileURL(join(source, '.opencode/plugins/hx-command-guard/index.js')).href);
  await plugin.default.setup(ctx);
  return { temp, cwd, callbacks, approvals, sha, base };
}

test('read-only Git inspection and independent attestations do not request plan approval', async () => {
  const setup = await environment();
  try {
    const git = setup.callbacks.get('hx_git_inspect');
    const inspected = JSON.parse((await git.execute({ action: 'commit', target: setup.sha })).content);
    assert.equal(inspected.sha, setup.sha);
    assert.equal(inspected.revision, setup.sha);
    assert.match(inspected.output, /after/);
    assert.equal(inspected.truncated, false);
    const content = JSON.parse((await git.execute({ action: 'file', target: setup.sha, path: 'app.txt' })).content);
    assert.equal(content.output.trim(), 'after');
    assert.equal(content.contentType, 'source');
    const fileDiff = JSON.parse((await git.execute({ action: 'file', base: setup.base,
      target: setup.sha, path: 'app.txt' })).content);
    assert.equal(fileDiff.contentType, 'diff');
    assert.equal(fileDiff.base, setup.base);
    assert.match(fileDiff.output, /-before/);
    assert.match(fileDiff.output, /\+after/);
    const files = JSON.parse((await git.execute({ action: 'files', target: setup.sha })).content);
    assert.match(files.output, /app.txt/);
    await assert.rejects(() => git.execute({ action: 'file', target: setup.sha, path: '../secret' }), /safe relative/);
    const report = { verdict: 'APPROVED', coverage: 'COMPLETE', scope: 'Reviewed app.txt at SHA', limitations: [], findings: [] };
    const submit = setup.callbacks.get('hx_submit_review');
    const first = JSON.parse((await submit.execute({ report, target: setup.sha }, context('reviewer'))).content);
    const second = JSON.parse((await submit.execute({ report, target: setup.sha }, context('security-auditor'))).content);
    assert.equal(first.mode, 'STANDALONE');
    assert.equal(second.mode, 'STANDALONE');
    assert.equal(setup.approvals.length, 0);
    assert.equal(existsSync(join(setup.cwd, '.hx')), false);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('range attestation uses same revision as read-only Git range', async () => {
  const setup = await environment();
  try {
    const git = setup.callbacks.get('hx_git_inspect');
    const diff = JSON.parse((await git.execute({ action: 'range', base: setup.base, target: setup.sha })).content);
    assert.match(diff.output, /after/);
    assert.equal(diff.revision.length, 64);
    const report = { verdict: 'APPROVED', coverage: 'COMPLETE', scope: 'Commit range reviewed', limitations: [], findings: [] };
    const submit = setup.callbacks.get('hx_submit_review');
    const outcome = JSON.parse((await submit.execute({ report, base: setup.base, target: setup.sha }, context('reviewer'))).content);
    assert.equal(outcome.mode, 'STANDALONE');
    assert.equal(outcome.target, diff.revision);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('CLI failures expose structured reason rather than generic Command failed', async () => {
  const setup = await environment();
  try {
    const manage = setup.callbacks.get('hx_manage');
    await assert.rejects(() => manage.execute({ action: 'verify' }, context('orchestrator')), /No active HX plan/);
    assert.equal(setup.approvals.length, 0);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('approval preflight blocks dirty checkout without presenting unusable prompt', async () => {
  const setup = await environment();
  try {
    mkdirSync(join(setup.cwd, '.hx'));
    const template = readFileSync(join(source, '.opencode/hx/templates/plan.example.md'), 'utf8');
    writeFileSync(join(setup.cwd, '.hx/plan.md'), template);
    const manage = setup.callbacks.get('hx_manage');
    await manage.execute({ action: 'submit' }, context('architect'));
    writeFileSync(join(setup.cwd, 'untracked.txt'), 'dirty');
    await assert.rejects(() => setup.callbacks.get('hx_approve_plan').execute({}, context('orchestrator')), /uncommitted changes/);
    assert.equal(setup.approvals.length, 0);
    const status = JSON.parse((await manage.execute({ action: 'status' }, context('orchestrator'))).content);
    assert.equal(status.status, 'DRAFT');
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('Git HEAD refs resolve to immutable SHAs and standalone reports use the same commit', async () => {
  const setup = await environment();
  try {
    const git = setup.callbacks.get('hx_git_inspect');
    const latest = JSON.parse((await git.execute({ action: 'commit', target: 'HEAD' })).content);
    assert.equal(latest.sha, setup.sha);
    assert.deepEqual(latest.parents, [setup.base]);
    const previous = JSON.parse((await git.execute({ action: 'commit', target: 'HEAD~1' })).content);
    assert.equal(previous.sha, setup.base);
    const shaAncestor = JSON.parse((await git.execute({ action: 'commit', target: `${setup.sha}~1` })).content);
    assert.equal(shaAncestor.sha, setup.base);
    const shaCaret = JSON.parse((await git.execute({ action: 'commit', target: `${setup.sha}^` })).content);
    assert.equal(shaCaret.sha, setup.base);
    const caret = JSON.parse((await git.execute({ action: 'commit', target: 'HEAD^' })).content);
    assert.equal(caret.sha, setup.base);
    const range = JSON.parse((await git.execute({ action: 'range', base: 'HEAD~1', target: 'HEAD' })).content);
    assert.equal(range.base, setup.base);
    assert.equal(range.target, setup.sha);
    const pinnedRange = JSON.parse((await git.execute({ action: 'range', base: `${setup.sha}~1`, target: setup.sha })).content);
    assert.equal(pinnedRange.base, setup.base);
    assert.equal(pinnedRange.target, setup.sha);
    const report = { verdict: 'APPROVED', coverage: 'COMPLETE', scope: 'Checked HEAD', limitations: [], findings: [] };
    const submitted = JSON.parse((await setup.callbacks.get('hx_submit_review').execute({
      report, target: 'HEAD',
    }, context('reviewer'))).content);
    assert.equal(submitted.mode, 'STANDALONE');
    assert.equal(submitted.target, setup.sha);
    const submittedRange = JSON.parse((await setup.callbacks.get('hx_submit_review').execute({
      report, base: 'HEAD~1', target: 'HEAD',
    }, context('security-auditor'))).content);
    assert.equal(submittedRange.target, range.revision);
    assert.equal(setup.approvals.length, 0);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('Git inspection rejects untrusted revision expressions instead of passing arbitrary flags', async () => {
  const setup = await environment();
  try {
    const git = setup.callbacks.get('hx_git_inspect');
    for (const value of ['--help', 'HEAD@{1}', 'HEAD:app.txt', 'HEAD~99999', 'main;echo hi', 'HEAD..HEAD', `${setup.sha}~1^2`, `${setup.sha}~1000`, `${setup.sha}:app.txt`, `${setup.sha}..HEAD`]) {
      await assert.rejects(() => git.execute({ action: 'commit', target: value }), /expected SHA or HEAD/);
    }
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('review tools publish the live schema, prevalidate anchors, and preserve partial coverage', async () => {
  const setup = await environment();
  try {
    const contract = setup.callbacks.get('hx_review_contract');
    const published = JSON.parse((await contract.execute({})).content);
    assert.ok(published.schema.required.includes('coverage'));
    assert.ok(published.schema.properties.findings.items.required.includes('anchor'));
    assert.equal(published.example.coverage, 'COMPLETE');

    const validate = setup.callbacks.get('hx_validate_review');
    const partial = {
      verdict: 'APPROVED', coverage: 'PARTIAL', scope: 'Reviewed app.txt at target commit',
      limitations: ['External dependency declarations were not available'],
      findings: [{ id: 'LOW-1', severity: 'LOW', file: 'app.txt', anchor: 'after',
        evidence: 'Confirmed the content of this commit', recommendation: 'Check related tests' }],
    };
    const checked = JSON.parse((await validate.execute({ report: partial, target: setup.sha }, context('reviewer'))).content);
    assert.equal(checked.valid, true);
    assert.equal(checked.report.findings[0].line, 1);
    assert.equal(partial.findings[0].line, undefined);

    const invalid = { ...partial, findings: [{ ...partial.findings[0], line: 1, anchor: 'before' }] };
    const rejected = JSON.parse((await validate.execute({ report: invalid, target: setup.sha }, context('reviewer'))).content);
    assert.equal(rejected.valid, false);
    assert.equal(rejected.issues[0].code, 'ANCHOR_MISMATCH');
    await assert.rejects(() => setup.callbacks.get('hx_submit_review').execute(
      { report: invalid, target: setup.sha }, context('reviewer')),
    /ANCHOR_MISMATCH/);
    const accepted = JSON.parse((await setup.callbacks.get('hx_submit_review').execute(
      { report: partial, target: setup.sha }, context('reviewer'))).content);
    assert.equal(accepted.verdict, 'APPROVED');
    assert.equal(accepted.coverage, 'PARTIAL');
    const stored = JSON.parse(readFileSync(accepted.saved_to, 'utf8'));
    assert.equal(stored.report.findings[0].line, 1);
    assert.equal(stored.report.coverage, 'PARTIAL');
    assert.equal(setup.approvals.length, 0);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});


test('explicit commit parent stays correct after HEAD advances', async () => {
  const setup = await environment();
  try {
    writeFileSync(join(setup.cwd, 'other.txt'), 'later\n');
    run(setup.cwd, ['add', '.']);
    run(setup.cwd, ['commit', '-qm', 'later']);
    const latest = run(setup.cwd, ['rev-parse', 'HEAD']);
    assert.notEqual(latest, setup.sha);
    const git = setup.callbacks.get('hx_git_inspect');
    const inspected = JSON.parse((await git.execute({ action: 'commit', target: setup.sha })).content);
    assert.equal(inspected.sha, setup.sha);
    assert.deepEqual(inspected.parents, [setup.base]);
    const ancestor = JSON.parse((await git.execute({ action: 'commit', target: `${setup.sha}~1` })).content);
    assert.equal(ancestor.sha, setup.base);
    const wrongHeadBase = JSON.parse((await git.execute({ action: 'commit', target: 'HEAD~1' })).content);
    assert.equal(wrongHeadBase.sha, setup.sha);
    assert.notEqual(inspected.parents[0], wrongHeadBase.sha);
    const diff = JSON.parse((await git.execute({ action: 'range', base: inspected.parents[0], target: inspected.sha })).content);
    assert.match(diff.output, /after/);
    const fileDiff = JSON.parse((await git.execute({ action: 'file', base: inspected.parents[0],
      target: inspected.sha, path: 'app.txt' })).content);
    assert.equal(fileDiff.contentType, 'diff');
    assert.match(fileDiff.output, /-before/);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});

test('merge commit exposes two immutable parents and SHA^2 resolves second parent', async () => {
  const setup = await environment();
  try {
    const originalBranch = run(setup.cwd, ['symbolic-ref', '--short', 'HEAD']);
    run(setup.cwd, ['checkout', '-qb', 'hx-topic', setup.base]);
    writeFileSync(join(setup.cwd, 'topic.txt'), 'topic\n');
    run(setup.cwd, ['add', '.']);
    run(setup.cwd, ['commit', '-qm', 'topic']);
    const secondParent = run(setup.cwd, ['rev-parse', 'HEAD']);
    run(setup.cwd, ['checkout', '-q', originalBranch]);
    run(setup.cwd, ['merge', '--no-ff', '-qm', 'merge topic', 'hx-topic']);
    const mergeSha = run(setup.cwd, ['rev-parse', 'HEAD']);
    const git = setup.callbacks.get('hx_git_inspect');
    const merged = JSON.parse((await git.execute({ action: 'commit', target: mergeSha })).content);
    assert.deepEqual(merged.parents, [setup.sha, secondParent]);
    const resolved = JSON.parse((await git.execute({ action: 'commit', target: `${mergeSha}^2` })).content);
    assert.equal(resolved.sha, secondParent);
    const first = JSON.parse((await git.execute({ action: 'commit', target: `${mergeSha}^` })).content);
    assert.equal(first.sha, setup.sha);
  } finally { rmSync(setup.temp, { recursive: true, force: true }); }
});
