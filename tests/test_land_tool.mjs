import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { registerWorkflowTools } from '../.opencode/plugins/hx-command-guard/workflow.js';

const root = resolve(import.meta.dirname, '..');
const python = process.env.HX_PYTHON || 'python3';
const source = join(root, '.opencode/hx');
const command = (cwd, executable, args) => execFileSync(executable, args, {
  cwd, encoding: 'utf8', windowsHide: true, timeout: 30000,
}).trim();
const git = (cwd, ...args) => command(cwd, 'git', args);
const py = (cwd, body) => command(cwd, python, ['-c',
  `import sys; sys.path.insert(0, ${JSON.stringify(source)}); ${body}`]);
const context = { agent: 'orchestrator', sessionID: 'hx-test-session',
  messageID: 'hx-test-message', id: 'hx-test-tool' };

test('hx_land previews, prompts separately for commit and merge, and never pushes', async () => {
  const temp = mkdtempSync(join(tmpdir(), 'hx-land-tool-'));
  try {
    const repo = join(temp, 'repo');
    const worktree = join(temp, 'worktree');
    mkdirSync(repo);
    git(repo, 'init', '-q');
    git(repo, 'config', 'user.name', 'HX Test');
    git(repo, 'config', 'user.email', 'hx@example.invalid');
    writeFileSync(join(repo, 'README.md'), 'base\n');
    git(repo, 'add', 'README.md');
    git(repo, 'commit', '-qm', 'base');
    mkdirSync(join(repo, '.hx'));
    writeFileSync(join(repo, '.hx/plan.md'), readFileSync(join(source, 'templates/plan.example.md')));
    py(repo, 'import state; state.register(__import__("pathlib").Path.cwd()); state.approve(__import__("pathlib").Path.cwd())');
    git(repo, 'worktree', 'add', '-qb', 'hx-test', worktree);
    py(repo, `import cli; from pathlib import Path; cli.attach(Path.cwd(), Path(${JSON.stringify(worktree)}))`);
    writeFileSync(join(worktree, 'README.md'), 'approved change\n');
    py(worktree, 'import cli,state; from pathlib import Path; p=Path.cwd(); data, task=state.current(p); r=state.workspace_revision(p); task.update(status="VERIFYING", checks="PASS", review="APPROVED", security="APPROVED", review_coverage="COMPLETE", security_coverage="COMPLETE", checks_revision=r, review_revision=r, security_revision=r); state.save(p,data); cli.can_complete(p)');

    const tools = new Map();
    const approvals = [];
    let deny = true;
    const ctx = {
      tool: { transform: async callback => callback({ add: tool => tools.set(tool.name, tool) }) },
      permission: { assert: async request => {
        approvals.push(request);
        if (deny) throw new Error('Permission denied by the user');
      } },
    };
    await registerWorkflowTools(ctx, repo, join(temp, 'state'));
    const land = tools.get('hx_land');
    assert.ok(land);
    const preview = JSON.parse((await land.execute({action:'preview',cwd:worktree},context)).content);
    assert.equal(preview.phase, 'PREVIEW');
    assert.deepEqual(preview.files,['README.md']);
    await assert.rejects(() => land.execute({action:'commit',cwd:worktree,manifest_sha256:preview.manifest_sha256},context), /denied/);
    assert.equal(git(repo,'rev-parse','HEAD'), git(worktree,'rev-parse','HEAD'));
    deny = false;
    const committed = JSON.parse((await land.execute({action:'commit',cwd:worktree,manifest_sha256:preview.manifest_sha256},context)).content);
    assert.equal(committed.phase, 'COMMITTED');
    const mergePreview = JSON.parse((await land.execute({action:'preview',cwd:worktree},context)).content);
    assert.equal(mergePreview.phase,'MERGE');
    const merged = JSON.parse((await land.execute({action:'merge',cwd:worktree,manifest_sha256:mergePreview.manifest_sha256},context)).content);
    assert.equal(merged.phase,'MERGED');
    assert.equal(readFileSync(join(repo,'README.md'),'utf8'),'approved change\n');
    assert.deepEqual(approvals.map(a=>a.action),['hx_land','hx_land','hx_land']);
    assert.equal(approvals[1].metadata.action,'commit');
    assert.equal(approvals[2].metadata.action,'merge');
    assert.equal(git(repo,'remote').trim(),'');
  } finally { rmSync(temp,{recursive:true,force:true}); }
});
