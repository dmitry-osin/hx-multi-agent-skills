import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, cpSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { setTimeout as sleep } from 'node:timers/promises';

const root = resolve(import.meta.dirname, '..');

function command(cwd, program, args) {
  const out = execFileSync(program, args, { cwd, encoding: 'utf8', timeout: 20000 });
  return out.trim();
}

function workflow(cwd, ...args) {
  return JSON.parse(command(cwd, 'python3', ['.opencode/hx/cli.py', ...args]));
}

async function fakeOpenCode() {
  const tmp = mkdtempSync(join(tmpdir(), 'hx-integration-'));
  const cwd = join(tmp, 'repo');
  mkdirSync(cwd);
  command(cwd, 'git', ['init', '-q']);
  command(cwd, 'git', ['config', 'user.name', 'HX Tester']);
  command(cwd, 'git', ['config', 'user.email', 'hx@example.invalid']);
  writeFileSync(join(cwd, 'README.md'), 'hello\n');
  command(cwd, 'git', ['add', 'README.md']);
  command(cwd, 'git', ['commit', '-qm', 'init']);
  cpSync(join(root, '.opencode'), join(cwd, '.opencode'), { recursive: true,
    filter: path => !path.includes('__pycache__') && !path.includes('node_modules'),
  });
  cpSync(join(root, 'opencode.jsonc'), join(cwd, 'opencode.jsonc'));
  mkdirSync(join(cwd, '.hx'));
  cpSync(join(root, '.opencode/hx/templates/plan.example.md'), join(cwd, '.hx/plan.md'));
  workflow(cwd, 'submit');
  const callbacks = new Map();
  const approvals = [];
  let rejectNext = false;
  const ctx = {
    location: { directory: cwd },
    permission: {
      hook: async () => {},
      assert: async request => {
        approvals.push(request);
        if (rejectNext) { rejectNext = false; throw new Error('User rejected'); }
      },
    },
    tool: { hook: async () => {}, transform: async callback => callback({ add: item => callbacks.set(item.name, item) }) },
    shell: { hook: async () => {} },
  };
  const plugin = await import(pathToFileURL(join(cwd, '.opencode/plugins/hx-command-guard/index.js')).href);
  await plugin.default.setup(ctx);
  return { tmp, cwd, callbacks, approvals, reject: () => { rejectNext = true; } };
}

const context = agent => ({ agent, sessionID: `${agent}-session`, messageID: `${agent}-message`, id: `${agent}-tool` });

test('plugin only approves exact plan after explicit human permission', async () => {
  const environment = await fakeOpenCode();
  try {
    const approve = environment.callbacks.get('hx_approve_plan');
    environment.reject();
    await assert.rejects(() => approve.execute({}, context('orchestrator')), /User rejected/);
    assert.equal(workflow(environment.cwd, 'status').status, 'DRAFT');
    const ok = await approve.execute({}, context('orchestrator'));
    assert.equal(JSON.parse(ok.content).status, 'APPROVED');
    assert.equal(environment.approvals[0].action, 'hx_approve');
    assert.ok(environment.approvals[0].resources[0].includes(':'));
    await assert.rejects(() => approve.execute({}, context('developer')), /Only orchestrator/);
  } finally { rmSync(environment.tmp, { recursive: true, force: true }); }
});

test('worktree gates and independent signed reviews complete in fake OpenCode', async () => {
  const env = await fakeOpenCode();
  try {
    await env.callbacks.get('hx_approve_plan').execute({}, context('orchestrator'));
    const worktree = join(env.tmp, 'worktree');
    command(env.cwd, 'git', ['worktree', 'add', '-qb', 'hx-integration', worktree]);
    workflow(env.cwd, 'attach', worktree);
    workflow(worktree, 'start');
    const gates = { gates: [{ name: 'safe-test', argv: ['/usr/bin/true'], cwd: '.' }] };
    writeFileSync(join(worktree, '.opencode/hx/quality-gates.json'), JSON.stringify(gates));
    const runChecks = env.callbacks.get('hx_run_checks');
    env.reject();
    await assert.rejects(() => runChecks.execute({ cwd: worktree }, context('orchestrator')), /User rejected/);
    assert.equal(workflow(worktree, 'status').checks, null);
    const started = JSON.parse((await runChecks.execute({ cwd: worktree }, context('orchestrator'))).content);
    assert.equal(started.status, 'STARTED');
    assert.ok(started.job_id);
    const getStatus = env.callbacks.get('hx_checks_status');
    let result;
    for (let attempt = 0; attempt < 160; attempt++) {
      result = JSON.parse((await getStatus.execute({ cwd: worktree, job_id: started.job_id })).content);
      if (!['QUEUED', 'RUNNING'].includes(result.status)) break;
      await sleep(100);
    }
    assert.equal(result.status, 'PASS', JSON.stringify(result));
    assert.equal(env.approvals.at(-1).action, 'hx_checks');
    assert.deepEqual(env.approvals.at(-1).metadata.gates[0].argv, ['/usr/bin/true']);
    const report = { verdict: 'APPROVED', coverage: 'COMPLETE', scope: 'Reviewed real source changes', limitations: [], findings: [] };
    const sign = env.callbacks.get('hx_submit_review');
    await assert.rejects(() => sign.execute({ cwd: worktree, report }, context('orchestrator')), /Only the dedicated/);
    await sign.execute({ cwd: worktree, report }, context('reviewer'));
    await sign.execute({ cwd: worktree, report }, context('security-auditor'));
    assert.equal(workflow(worktree, 'complete').status, 'COMPLETED');
    assert.equal(workflow(worktree, 'status').status, 'COMPLETED');
    const signed = readdirSync(join(worktree, '.hx/reports')).find(name => name.startsWith('review.') && name.endsWith('.signed.json'));
    assert.ok(signed);
    assert.ok(readFileSync(join(worktree, '.hx/reports', signed), 'utf8').includes('signature'));
  } finally { rmSync(env.tmp, { recursive: true, force: true }); }
});
