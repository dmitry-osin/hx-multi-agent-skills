import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, cpSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const root = resolve(import.meta.dirname, '..');
const py = process.env.HX_PYTHON || 'python3';
const run = (cwd, cmd, args) => execFileSync(cmd, args, { cwd, encoding: 'utf8', timeout: 30000 }).trim();

function repo(cwd) {
  mkdirSync(cwd);
  run(cwd, 'git', ['init', '-q']);
  run(cwd, 'git', ['config', 'user.name', 'HX Tester']);
  run(cwd, 'git', ['config', 'user.email', 'hx@example.invalid']);
  writeFileSync(join(cwd, 'README.md'), 'project\n');
  run(cwd, 'git', ['add', 'README.md']);
  run(cwd, 'git', ['commit', '-qm', 'init']);
}

const context = agent => ({ agent, sessionID: `${agent}-session`, messageID: `${agent}-message`, id: `${agent}-tool` });

test('global plugin resolves tools outside checkout, prompts, and does not copy config to worktree', async () => {
  const temp = mkdtempSync(join(tmpdir(), 'hx-global-plugin-'));
  try {
    const target = join(temp, 'user-config');
    const project = join(temp, 'repo');
    repo(project);
    run(root, py, ['install.py', 'global', '--target', target]);
    assert.equal(existsSync(join(project, '.opencode')), false);
    mkdirSync(join(project, '.hx'));
    cpSync(join(root, '.opencode/hx/templates/plan.example.md'), join(project, '.hx/plan.md'));
    const callbacks = new Map();
    const approvals = [];
    const ctx = {
      location: { directory: project },
      permission: {
        hook: async () => {},
        assert: async item => { approvals.push(item); },
      },
      shell: { hook: async () => {} },
      tool: { hook: async () => {}, transform: async cb => cb({ add: tool => callbacks.set(tool.name, tool) }) },
    };
    const plugin = await import(pathToFileURL(join(target, 'plugins/hx-command-guard/index.js')).href);
    await plugin.default.setup(ctx);
    assert.ok(callbacks.has('hx_manage'));
    assert.ok(callbacks.has('hx_approve_plan'));
    assert.ok(callbacks.has('hx_guard_info'));
    assert.ok(callbacks.has('hx_review_contract'));
    assert.ok(callbacks.has('hx_validate_review'));
    const draft = JSON.parse((await callbacks.get('hx_manage').execute({ action: 'submit' }, context('architect'))).content);
    assert.equal(draft.status, 'DRAFT');
    const approved = JSON.parse((await callbacks.get('hx_approve_plan').execute({}, context('orchestrator'))).content);
    assert.equal(approved.status, 'APPROVED');
    assert.equal(approvals[0].action, 'hx_approve');
    const worktree = join(temp, 'feature');
    run(project, 'git', ['worktree', 'add', '-qb', 'hx-feature', worktree]);
    const attached = JSON.parse((await callbacks.get('hx_manage').execute({ action: 'attach', argument: worktree }, context('orchestrator'))).content);
    assert.equal(attached.worktree, worktree);
    assert.equal(existsSync(join(worktree, '.opencode')), false);
    const result = JSON.parse((await callbacks.get('hx_manage').execute({ action: 'start', cwd: worktree }, context('orchestrator'))).content);
    assert.equal(result.status, 'IMPLEMENTING');
    const guard = JSON.parse((await callbacks.get('hx_guard_info').execute({ action: 'status' })).content);
    assert.equal(guard.last_plugin_load.version, '5.8.0');
  } finally { rmSync(temp, { recursive: true, force: true }); }
});

test('project-local guard takes priority when both installations are present', async () => {
  const temp = mkdtempSync(join(tmpdir(), 'hx-dual-install-'));
  try {
    const globalDir = join(temp, 'config');
    const project = join(temp, 'project');
    repo(project);
    run(root, py, ['install.py', 'global', '--target', globalDir]);
    run(root, py, ['install.py', 'local', '--target', project]);
    const tools = new Map();
    let count = 0;
    const ctx = {
      location: { directory: project },
      permission: { hook: async () => { count++; }, assert: async () => {} },
      shell: { hook: async () => { count++; } },
      tool: { hook: async () => { count++; }, transform: async cb => cb({ add: action => tools.set(action.name, action) }) },
    };
    const globalPlugin = await import(pathToFileURL(join(globalDir, 'plugins/hx-command-guard/index.js')).href);
    const localPlugin = await import(pathToFileURL(join(project, '.opencode/plugins/hx-command-guard/index.js')).href);
    await globalPlugin.default.setup(ctx);
    assert.equal(tools.size, 0);
    await localPlugin.default.setup(ctx);
    assert.ok(tools.has('hx_manage'));
    assert.ok(count > 0);
  } finally { rmSync(temp, { recursive: true, force: true }); }
});
