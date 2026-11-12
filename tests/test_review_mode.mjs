import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, cpSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const root = resolve(import.meta.dirname, '..');
const run = (cwd, program, args, options = {}) => execFileSync(program, args, {
  cwd, encoding: 'utf8', timeout: 20000, windowsHide: true, ...options,
}).trim();
const context = agent => ({ agent, sessionID: `${agent}-session`, messageID: `${agent}-message`, id: `${agent}-tool` });

async function environment() {
  const temp = mkdtempSync(join(tmpdir(), 'hx-review-mode-'));
  const repo = join(temp, 'repo');
  mkdirSync(repo);
  run(repo, 'git', ['init', '-q']);
  run(repo, 'git', ['config', 'user.name', 'HX Tester']);
  run(repo, 'git', ['config', 'user.email', 'hx@example.invalid']);
  writeFileSync(join(repo, 'README.md'), 'old source\n');
  run(repo, 'git', ['add', 'README.md']);
  run(repo, 'git', ['commit', '-qm', 'base']);
  const base = run(repo, 'git', ['rev-parse', 'HEAD']);
  cpSync(join(root, '.opencode'), join(repo, '.opencode'), {
    recursive: true, filter: name => !name.includes('__pycache__') && !name.includes('node_modules'),
  });
  mkdirSync(join(repo, '.hx'));
  cpSync(join(root, '.opencode/hx/templates/plan.example.md'), join(repo, '.hx/plan.md'));
  const cli = (...args) => JSON.parse(run(repo, 'python3', [join(repo, '.opencode/hx/cli.py'), ...args]));
  console.error('stage submit');
  const submitted = cli('submit');
  // Simulate the explicit approval that the OpenCode plugin obtains from the user.
  console.error('stage approve');
  const accepted = JSON.parse(run(repo, 'python3', [join(repo, '.opencode/hx/cli.py'),
    'approve', '--task-id', submitted.id, '--human-confirm', `${submitted.id}:${submitted.sha256.slice(0, 12)}`],
    { env: { ...process.env, HX_PLUGIN_APPROVED: '1' } }));
  assert.equal(accepted.status, 'APPROVED');
  console.error('stage worktree');
  const worktree = join(temp, 'worktree');
  run(repo, 'git', ['worktree', 'add', '-qb', 'hx-reviewed', worktree]);
  cli('attach', worktree);
  JSON.parse(run(worktree, 'python3', [join(repo, '.opencode/hx/cli.py'), 'start']));
  const untrackedFile = 'cards-mediator-impl/TraceContextJobDataMapSupport.java';
  mkdirSync(join(worktree, 'cards-mediator-impl'));
  writeFileSync(join(worktree, untrackedFile),
    'class TraceContextJobDataMapSupport {\n  void captureCurrentContext() {}\n}\n');
  const callbacks = new Map();
  const ctx = { location: { directory: repo },
    permission: { hook: async () => {}, assert: async () => {} },
    shell: { hook: async () => {} },
    tool: { hook: async () => {}, transform: async register => register({ add: item => callbacks.set(item.name, item) }) },
  };
  const module = await import(pathToFileURL(join(repo, '.opencode/plugins/hx-command-guard/index.js')).href);
  console.error('stage plugin');
  await module.default.setup(ctx);
  console.error('stage plugin ready');
  return { temp, repo, worktree, base, callbacks, untrackedFile };
}

test('formal review of new untracked file omits base/target, validates and persists', async () => {
  const env = await environment();
  try {
    const contractTool = env.callbacks.get('hx_review_contract');
    console.error('stage contract');
    const contract = JSON.parse((await contractTool.execute({ cwd: env.worktree })).content);
    assert.equal(contract.review_mode, 'FORMAL');
    assert.match(contract.invocation, /omit target\/base/);
    const report = {
      verdict: 'CHANGES_REQUESTED', coverage: 'COMPLETE', scope: 'Reviewed new tracking class',
      limitations: [], findings: [{ id: 'F1', severity: 'MEDIUM', file: env.untrackedFile,
        anchor: 'void captureCurrentContext() {}', evidence: 'Not called by production code',
        recommendation: 'Call this when Quartz jobs are scheduled' }],
    };
    const validate = env.callbacks.get('hx_validate_review');
    console.error('stage preflight');
    const checked = JSON.parse((await validate.execute({ cwd: env.worktree, mode: 'FORMAL', report }, context('reviewer'))).content);
    assert.equal(checked.valid, true, JSON.stringify(checked));
    assert.equal(checked.report.findings[0].line, 2);
    const signed = env.callbacks.get('hx_submit_review');
    console.error('stage submit-review');
    const recorded = JSON.parse((await signed.execute({ cwd: env.worktree,
      mode: 'FORMAL', report }, context('reviewer'))).content);
    console.error('stage signed', recorded.review);
    assert.equal(recorded.review, 'CHANGES_REQUESTED');
    const file = JSON.parse(readFileSync(join(env.repo, '.git/hx/reports', JSON.parse(run(env.worktree, 'python3', [join(env.repo, '.opencode/hx/cli.py'), 'status'])).id, 'review.json'), 'utf8'));
    assert.equal(file.report.findings[0].line, 2);
  } finally { rmSync(env.temp, { recursive: true, force: true }); }
});

