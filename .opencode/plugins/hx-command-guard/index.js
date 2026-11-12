import { existsSync, mkdirSync, writeFileSync, appendFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { join, resolve, isAbsolute, dirname } from 'node:path';
import { homedir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { digestResources } from './guard.js';
import { registerWorkflowTools } from './workflow.js';

const INSTALL_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..');

function securityDir(project) {
  try {
    const output = execFileSync('git', ['rev-parse', '--git-common-dir'], {
      cwd: project, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true,
    }).trim();
    const directory = isAbsolute(output) ? output : resolve(project, output);
    return join(directory, 'hx', 'security');
  } catch {
    const stateBase = process.platform === 'win32'
      ? (process.env.LOCALAPPDATA || join(homedir(), 'AppData', 'Local'))
      : (process.env.XDG_STATE_HOME || join(homedir(), '.local', 'state'));
    const suffix = createHash('sha256').update(resolve(project)).digest('hex').slice(0, 16);
    return join(stateBase, 'opencode-hx', suffix, 'security');
  }
}

function audit(directory, record) {
  mkdirSync(directory, { recursive: true, mode: 0o700 });
  appendFileSync(join(directory, 'guard.jsonl'), JSON.stringify({
    at: new Date().toISOString(), ...record,
  }) + '\n', { mode: 0o600 });
}

export default {
  id: 'hx-command-guard',
  async setup(ctx) {
    let project = ctx.location.directory;
    try {
      project = execFileSync('git', ['rev-parse', '--show-toplevel'], {
        cwd: project, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true,
      }).trim();
    } catch { /* Keep non-Git workspaces functional; HX planning requires Git. */ }
    const localPlugin = join(project, '.opencode', 'plugins', 'hx-command-guard', 'index.js');
    // When global and local copies coexist, only the local plugin registers hooks.
    if (INSTALL_ROOT !== resolve(project, '.opencode') && existsSync(localPlugin)) return;
    const directory = securityDir(project);
    await registerWorkflowTools(ctx, project, join(securityDir(project), '..'));
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    writeFileSync(join(directory, 'status.json'), JSON.stringify({
      loaded: true,
      loadedAt: new Date().toISOString(),
      project,
      permission_mode: 'native-opencode',
      version: '5.8.0',
      installRoot: INSTALL_ROOT,
    }, null, 2), { mode: 0o600 });

    // Deliberately no permission or shell hooks: native OpenCode decisions are authoritative.
    await ctx.tool.hook('execute.before', (event) => {
      // Do not alter the command or silently approve tool actions here.
      const tool = String(event.tool ?? 'unknown');
      audit(directory, { kind: 'tool-before', tool, inputSha256: digestResources(event.input) });
    });

    await ctx.tool.hook('execute.after', (event) => {
      audit(directory, {
        kind: 'tool-after', tool: String(event.tool ?? 'unknown'),
        status: event.status ?? 'unknown',
      });
    });
  },
};
