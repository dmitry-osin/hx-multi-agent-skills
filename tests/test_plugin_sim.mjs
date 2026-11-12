import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, copyFileSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const original = resolve(import.meta.dirname, '../.opencode/plugins/hx-command-guard');

async function setupFake() {
  const temp = mkdtempSync(join(tmpdir(), 'hx-plugin-native-'));
  const repo = join(temp, 'repo');
  mkdirSync(repo);
  execFileSync('git', ['init', '-q'], { cwd: repo });
  const plugin = join(repo, '.opencode/plugins/hx-command-guard');
  mkdirSync(plugin, { recursive: true });
  for (const name of ['guard.js', 'index.js', 'workflow.js', 'git-inspect.js', 'checks-jobs.js']) {
    copyFileSync(join(original, name), join(plugin, name));
  }
  writeFileSync(join(plugin, 'package.json'), '{"type":"module"}');
  const hooks = {};
  const registered = new Map();
  const ctx = {
    location: { directory: repo },
    permission: { hook: async (key, cb) => { hooks[`permission.${key}`] = cb; } },
    shell: { hook: async (key, cb) => { hooks[`shell.${key}`] = cb; } },
    tool: {
      hook: async (key, cb) => { hooks[`tool.${key}`] = cb; },
      transform: async (callback) => callback({ add: (tool) => registered.set(tool.name, tool) }),
    },
  };
  const mod = await import(pathToFileURL(join(plugin, 'index.js')).href);
  await mod.default.setup(ctx);
  return { temp, repo, hooks, registered };
}

test('HX does not override OpenCode native shell, edit, Code Mode or MCP decisions', async () => {
  const state = await setupFake();
  try {
    assert.equal(state.hooks['permission.evaluate'], undefined);
    assert.equal(state.hooks['shell.create.before'], undefined);
    assert.ok(state.registered.has('hx_manage'));
    assert.ok(state.registered.has('hx_run_checks'));
    assert.ok(state.registered.has('hx_checks_status'));
    assert.ok(state.registered.has('hx_submit_review'));
    assert.ok(state.registered.has('hx_git_inspect'));
    const record = JSON.parse(readFileSync(join(state.repo, '.git/hx/security/status.json'), 'utf8'));
    assert.equal(record.permission_mode, 'native-opencode');
  } finally {
    rmSync(state.temp, { recursive: true, force: true });
  }
});

test('HX keeps sanitized tool activity logs without changing tool calls', async () => {
  const state = await setupFake();
  try {
    const before = { tool: 'shell', input: { command: 'echo sample-secret' } };
    const after = { tool: 'shell', status: 'ok' };
    state.hooks['tool.execute.before'](before);
    state.hooks['tool.execute.after'](after);
    const log = readFileSync(join(state.repo, '.git/hx/security/guard.jsonl'), 'utf8');
    assert.ok(log.includes('inputSha256'));
    assert.ok(!log.includes('sample-secret'));
    assert.ok(log.includes('tool-after'));
  } finally {
    rmSync(state.temp, { recursive: true, force: true });
  }
});
