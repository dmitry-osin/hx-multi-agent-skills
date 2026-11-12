"use strict";

import { createHmac, createHash, randomBytes } from 'node:crypto';
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { resolve, join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { inspectGit } from './git-inspect.js';
import { checksStatus, startChecks } from './checks-jobs.js';

const HX_HOME = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', 'hx');
const PYTHON_COMMANDS = process.platform === 'win32'
  ? [['py', ['-3']], ['python', []], ['python3', []]]
  : [['python3', []], ['python', []]];

function pythonCommand() {
  const available = process.env.HX_PYTHON ? [[process.env.HX_PYTHON, []]] : PYTHON_COMMANDS;
  for (const [program, prefix] of available) {
    try {
      const output = execFileSync(program, [...prefix, '-c', 'import sys; print(sys.version_info.major)'], {
        encoding: 'utf8', timeout: 5000, stdio: ['ignore', 'pipe', 'ignore'], windowsHide: true,
      });
      if (output.trim() === '3') return [program, prefix];
    } catch { /* Try the next configured Python launcher. */ }
  }
  throw new Error('HX requires Python 3.10+ (set HX_PYTHON to its executable path)');
}

function executeScript(cwd, script, args, env = {}, stdin = null) {
  const [program, prefix] = pythonCommand();
  let out;
  try {
    out = execFileSync(program, [...prefix, join(HX_HOME, script), ...args], {
      cwd, encoding: 'utf8', env: { ...process.env, ...env }, timeout: 630000,
      stdio: ['pipe', 'pipe', 'pipe'], windowsHide: true, input: stdin ?? undefined,
    });
  } catch (error) {
    const stdout = String(error.stdout ?? '').trim();
    const stderr = String(error.stderr ?? '').trim();
    let explanation = stderr;
    try {
      const failed = JSON.parse(stdout);
      explanation = failed.error ?? explanation;
      if (Array.isArray(failed.issues) && failed.issues.length) {
        explanation += '\n' + failed.issues.map(item =>
          `${item.path} [${item.code}]: ${item.message}`).join('\n');
      }
    } catch { /* Use stderr. */ }
    throw new Error(`HX CLI failed (${script}, ${args[0]}, exit ${error.status ?? 'unknown'}): ${explanation || stdout || error.message}`);
  }
  let data;
  try { data = JSON.parse(out); } catch {
    throw new Error(`HX CLI returned invalid JSON for ${script}: ${String(out).slice(0, 350)}`);
  }
  if (data.error) throw new Error(`HX: ${data.error}`);
  return data;
}

function executeCli(cwd, args, env = {}, stdin = null) {
  return executeScript(cwd, 'cli.py', args, env, stdin);
}

function projectCwd(input, canonical) {
  const requested = resolve(input.cwd || canonical);
  const gitCommon = (cwd) => resolve(cwd, execFileSync('git', ['rev-parse', '--git-common-dir'], {
    cwd, encoding: 'utf8', timeout: 3000, windowsHide: true,
  }).trim());
  if (gitCommon(requested) !== gitCommon(canonical)) throw new Error('HX tool only accepts worktrees of this repository');
  return requested;
}

function attestationKey(directory) {
  const filename = join(directory, 'attest.key');
  if (!existsSync(filename)) {
    mkdirSync(directory, { recursive: true, mode: 0o700 });
    try {
      writeFileSync(filename, randomBytes(32), { flag: 'wx', mode: 0o600 });
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
    }
  }
  return readFileSync(filename);
}

function source(context) {
  if (!context.sessionID || !context.messageID || !context.id) {
    throw new Error('HX requires a real OpenCode tool-call session context');
  }
  return { type: 'tool', messageID: context.messageID, id: context.id };
}

function mustBeOrchestrator(context) {
  if (context.agent !== 'orchestrator') throw new Error('Only orchestrator can request HX approvals/checks');
}


function reviewSchema() {
  return JSON.parse(readFileSync(join(HX_HOME, 'review-schema.json'), 'utf8'));
}

function reviewExample() {
  return {
    verdict: 'APPROVED', coverage: 'COMPLETE',
    scope: 'Reviewed the changed files and relevant tests', limitations: [], findings: [],
  };
}

function prevalidateReport(cwd, report, { formal, target }) {
  const args = ['review-validate'];
  if (formal) args.push('--formal');
  if (target && !formal) args.push('--target', target);
  return executeCli(cwd, args, {}, JSON.stringify(report));
}

const FORMAL_REVIEW_STATES = new Set(['IMPLEMENTING', 'VERIFYING', 'BLOCKED']);

function reviewContext(cwd, input = {}) {
  const status = executeCli(cwd, ['status']);
  const active = FORMAL_REVIEW_STATES.has(status.status);
  const references = [input.target, input.base].filter(Boolean);
  if (references.some(value => /^[a-fA-F0-9]{64}$/.test(value))) {
    throw new Error('A 64-character HX workspace revision is not a Git commit SHA. ' +
      'For FORMAL review omit target and base; HX binds the current worktree revision automatically.');
  }
  if (input.mode === 'FORMAL' && !active) {
    throw new Error('FORMAL review requires an active approved HX task in its worktree.');
  }
  if (active && references.length && input.mode !== 'STANDALONE') {
    throw new Error('Active HX task: FORMAL review must omit target and base, including the plan base_commit. ' +
      'New files exist in the worktree but not in the base commit. ' +
      'For an intentional independent Git audit specify mode: STANDALONE.');
  }
  if (input.mode === 'FORMAL' && references.length) {
    throw new Error('FORMAL review must omit target and base.');
  }
  if (input.base && !input.target) throw new Error('A standalone range requires both base and target.');
  const formal = input.mode === 'FORMAL' || (active && input.mode !== 'STANDALONE');
  return { formal, mode: formal ? 'FORMAL' : 'STANDALONE', status };
}

export async function registerWorkflowTools(ctx, canonical, directory) {
  await ctx.tool.transform((editor) => {
    editor.add({
      name: 'hx_manage',
      description: 'Run a known HX workflow action from the installed global or project HX runtime; never arbitrary shell.',
      input: { type: 'object', properties: {
        action: { type: 'string', enum: ['submit', 'status', 'verify', 'attach', 'start', 'cycle', 'complete', 'diff', 'pr', 'cost', 'revision'] },
        cwd: { type: 'string' },
        argument: { type: 'string' },
      }, required: ['action'], additionalProperties: false },
      execute: async (input, context) => {
        const cwd = projectCwd(input, canonical);
        const mutations = new Set(['attach', 'start', 'cycle', 'complete', 'pr']);
        if (mutations.has(input.action)) mustBeOrchestrator(context);
        if (input.action === 'submit' && context.agent !== 'architect') {
          throw new Error('Only architect can register draft plans');
        }
        if (input.action === 'attach' && !input.argument) {
          throw new Error('attach needs a worktree path');
        }
        const args = [input.action];
        if (input.action === 'attach' || (input.action === 'diff' && input.argument)) args.push(input.argument);
        return { content: JSON.stringify(executeCli(cwd, args)) };
      },
    });
    editor.add({
      name: 'hx_land',
      description: 'Land a COMPLETED HX task: preview, separately approve commit and merge, optionally prepare a local PR draft or remove the merged worktree. Never pushes.',
      input: { type: 'object', properties: {
        action: { type: 'string', enum: ['preview', 'commit', 'merge', 'pr', 'cleanup'] },
        cwd: { type: 'string' },
        target_branch: { type: 'string' },
        strategy: { type: 'string', enum: ['merge', 'pr'] },
        legacy_override: { type: 'boolean' },
        manifest_sha256: { type: 'string' },
      }, required: ['action'], additionalProperties: false },
      execute: async (input, context) => {
        mustBeOrchestrator(context);
        const cwd = projectCwd(input, canonical);
        const previewArgs = ['land-preview'];
        if (input.target_branch) previewArgs.push('--land-target', input.target_branch);
        if (input.strategy) previewArgs.push('--land-strategy', input.strategy);
        if (input.legacy_override) previewArgs.push('--land-legacy-override');
        if (input.action === 'preview') {
          return { content: JSON.stringify(executeCli(cwd, previewArgs)) };
        }
        const commands = {
          commit: 'land-commit', merge: 'land-merge',
          pr: 'land-pr', cleanup: 'land-cleanup',
        };
        let preview;
        if (input.action === 'commit' || input.action === 'merge') {
          if (!input.manifest_sha256) throw new Error('First call hx_land preview and provide manifest_sha256');
          preview = executeCli(cwd, previewArgs);
          const requiredPhase = input.action === 'commit' ? 'PREVIEW' : 'MERGE';
          if (preview.phase !== requiredPhase || preview.manifest_sha256 !== input.manifest_sha256) {
            throw new Error('HX land preview is stale; request a fresh preview');
          }
        }
        const resource = preview?.manifest_sha256 ?? `${cwd}:${input.action}`;
        const legacyManual = input.action === 'commit' && preview?.proof === 'LEGACY_MANUAL';
        await ctx.permission.assert({
          sessionID: context.sessionID, agent: context.agent, source: source(context),
          action: legacyManual ? 'hx_land_legacy' : 'hx_land', resources: [resource], save: [],
          metadata: {
            action: input.action, source: cwd,
            target_branch: preview?.target_branch ?? input.target_branch,
            changed_files: preview?.files,
            warning: legacyManual
              ? 'LEGACY UNVERIFIED: source could not be cryptographically tied to the old approved revision. Review diff manually before allowing this commit.'
              : 'Git commit, merge or worktree removal modifies repository state. No push.',
          },
        });
        const args = [commands[input.action]];
        if (input.manifest_sha256) args.push('--land-sha', input.manifest_sha256);
        if (input.target_branch) args.push('--land-target', input.target_branch);
        if (input.strategy) args.push('--land-strategy', input.strategy);
        if (input.legacy_override) args.push('--land-legacy-override');
        return { content: JSON.stringify(executeCli(cwd, args)) };
      },
    });
    editor.add({
      name: 'hx_git_inspect',
      description: 'Read-only Git inspection of a commit SHA, commit range, working diff or status. Never modifies the repository; no formal HX plan needed.',
      input: { type: 'object', properties: {
        action: { type: 'string', enum: ['status', 'working', 'commit', 'range', 'file', 'files'] },
        cwd: { type: 'string' }, target: { type: 'string' }, base: { type: 'string' }, path: { type: 'string' },
      }, required: ['action'], additionalProperties: false },
      execute: async (input) => {
        const cwd = projectCwd(input, canonical);
        try { return { content: JSON.stringify(inspectGit(cwd, input)) }; }
        catch (error) { throw new Error(`HX Git inspection failed: ${error.message}`); }
      },
    });
    editor.add({
      name: 'hx_guard_info',
      description: 'Read the per-repository HX Guard status or sanitized audit log.',
      input: { type: 'object', properties: {
        action: { type: 'string', enum: ['status', 'log'] }, cwd: { type: 'string' },
      }, required: ['action'], additionalProperties: false },
      execute: async (input) => {
        const cwd = projectCwd(input, canonical);
        return { content: JSON.stringify(executeScript(cwd, 'guard/guard_cli.py', [input.action])) };
      },
    });
    editor.add({
      name: 'hx_approve_plan',
      description: 'Request an explicit human permission for the exact HX plan digest before approval. Never approve silently.',
      input: { type: 'object', properties: { cwd: { type: 'string' } }, additionalProperties: false },
      execute: async (input, context) => {
        mustBeOrchestrator(context);
        const cwd = projectCwd(input, canonical);
        // Preflight prevents prompting for an approval that cannot be applied.
        const current = executeCli(cwd, ['approve-preflight']);
        const resource = `${current.id}:${current.sha256.slice(0, 12)}`;
        await ctx.permission.assert({ sessionID: context.sessionID, agent: context.agent,
          source: source(context), action: 'hx_approve', resources: [resource],
          metadata: { plan_title: current.title, plan_version: current.version, plan_hash: current.sha256 }, save: [] });
        const output = executeCli(cwd, ['approve', '--task-id', current.id, '--human-confirm', resource], { HX_PLUGIN_APPROVED: '1' });
        return { content: JSON.stringify(output) };
      },
    });
    editor.add({
      name: 'hx_run_checks',
      description: 'Preview immutable Quality Gate manifest, request OpenCode permission, then start an independent background worker. Returns STARTED and job_id; poll hx_checks_status for PASS or FAIL.',
      input: { type: 'object', properties: { cwd: { type: 'string' } }, additionalProperties: false },
      execute: async (input, context) => {
        mustBeOrchestrator(context);
        const cwd = projectCwd(input, canonical);
        const existing = checksStatus(directory, cwd);
        if (existing.status === 'RUNNING' || existing.status === 'QUEUED') {
          return { content: JSON.stringify({ ...existing, already_running: true }) };
        }
        const preview = executeCli(cwd, ['checks-preview']);
        await ctx.permission.assert({ sessionID: context.sessionID, agent: context.agent,
          source: source(context), action: 'hx_checks', resources: [preview.sha256], save: [preview.sha256],
          metadata: { gates: preview.gates, project: cwd, warning: 'Build scripts can spawn arbitrary subprocesses; host mode is not sandboxed' } });
        const started = await startChecks({ directory, cwd, preview, pythonCommand, hxHome: HX_HOME });
        return { content: JSON.stringify(started) };
      },
    });
    editor.add({
      name: 'hx_checks_status',
      description: 'Read durable Quality Gate job status (RUNNING, PASS, FAIL, ERROR) after hx_run_checks. Does not start another build or require a permission prompt.',
      input: { type: 'object', properties: { cwd: { type: 'string' }, job_id: { type: 'string' } }, additionalProperties: false },
      execute: async (input) => {
        const cwd = projectCwd(input, canonical);
        return { content: JSON.stringify(checksStatus(directory, cwd, input.job_id)) };
      },
    });
    editor.add({
      name: 'hx_review_contract',
      description: 'Read the authoritative review schema and determine FORMAL vs STANDALONE mode before inspecting findings. For approved HX tasks use cwd of worktree and omit target/base.',
      input: { type: 'object', properties: { cwd: { type: 'string' } }, additionalProperties: false },
      execute: async (input) => {
        const cwd = projectCwd(input, canonical);
        const selected = reviewContext(cwd);
        return { content: JSON.stringify({
          schema: reviewSchema(), example: reviewExample(),
          review_mode: selected.mode, task_status: selected.status.status,
          invocation: selected.formal
            ? 'FORMAL: use mode: FORMAL, cwd of the approved worktree, and omit target/base from validate and submit. Source anchors are checked in this worktree, including newly added/untracked files.'
            : 'STANDALONE: use mode: STANDALONE, and supply a real Git SHA for target (plus base for ranges) or omit both for workspace review. For ranges, source anchors refer to TARGET, never BASE.',
          rules: ['Reserve steps for hx_validate_review and hx_submit_review; submit before optional deep exploration.',
            'Never pass the 64-digit HX workspace revision as target; it is not a Git commit.',
            'A parent/base Git SHA does not contain files introduced later in the task.',
            'Use only exact source anchors; never invent line numbers.',
            'A missing line is allowed when an anchor uniquely identifies a source line.',
            'COMPLETE requires no limitations; PARTIAL and BLOCKED require limitations.',
            'APPROVED+PARTIAL is allowed for the inspected scope; formal completion requires COMPLETE.',
            'APPROVED cannot contain CRITICAL/HIGH/MEDIUM findings or BLOCKED coverage.'],
        }) };
      },
    });
    editor.add({
      name: 'hx_validate_review',
      description: 'Validate review schema, coverage semantics, and exact file/line source anchors without saving a report.',
      input: { type: 'object', properties: {
        cwd: { type: 'string' }, report: { type: 'object' },
        mode: { type: 'string', enum: ['FORMAL', 'STANDALONE'] },
        target: { type: 'string' }, base: { type: 'string' },
      }, required: ['report'], additionalProperties: false },
      execute: async (input, context) => {
        const kind = context.agent === 'reviewer' ? 'review' : context.agent === 'security-auditor' ? 'security' : null;
        if (!kind) throw new Error('Only reviewer/security-auditor can prevalidate reviews');
        const cwd = projectCwd(input, canonical);
        const { formal } = reviewContext(cwd, input);
        const checked = input.target ? inspectGit(cwd, {
          action: input.base ? 'range' : 'commit', target: input.target, base: input.base,
        }) : null;
        const result = prevalidateReport(cwd, input.report, { formal, target: checked?.sha ?? checked?.target });
        return { content: JSON.stringify(result) };
      },
    });
    editor.add({
      name: 'hx_submit_review',
      description: 'Record a reviewer/security-auditor report with validated session/agent provenance and source revision.',
      input: {
        type: 'object', properties: {
          cwd: { type: 'string' },
          report: { type: 'object' }, mode: { type: 'string', enum: ['FORMAL', 'STANDALONE'] },
          target: { type: 'string' }, base: { type: 'string' },
        }, required: ['report'], additionalProperties: false,
      },
      execute: async (input, context) => {
        const kind = context.agent === 'reviewer' ? 'review' : context.agent === 'security-auditor' ? 'security' : null;
        if (!kind) throw new Error('Only the dedicated independent reviewer/security-auditor may record a verdict');
        source(context);
        const cwd = projectCwd(input, canonical);
        const { formal } = reviewContext(cwd, input);
        let payload;
        let command;
        let resolvedTarget = input.target;
        let resolvedBase = input.base;
        if (formal) {
          const revision = executeCli(cwd, ['revision']);
          payload = { agent: context.agent, session_id: context.sessionID, message_id: context.messageID,
            task_id: revision.task_id, workspace_revision: revision.sha256, report: input.report };
          command = ['review'];
        } else {
          if (input.base && !input.target) throw new Error('A commit range requires both base and target SHA');
          const targetKind = input.base ? 'range' : input.target ? 'commit' : 'workspace';
          const inspected = input.base
            ? inspectGit(cwd, { action: 'range', base: input.base, target: input.target })
            : input.target ? inspectGit(cwd, { action: 'commit', target: input.target }) : null;
          // Store a stable commit identity, never a moving symbolic ref such as HEAD.
          resolvedTarget = inspected?.sha ?? inspected?.target ?? input.target;
          resolvedBase = inspected?.base ?? input.base;
          const targetSha = inspected?.revision ?? executeCli(cwd, ['revision']).sha256;
          payload = { agent: context.agent, session_id: context.sessionID, message_id: context.messageID,
            target_kind: targetKind, target_sha256: targetSha, report: input.report };
          command = ['standalone-review'];
        }
        // Validate before writing signed input; CLI repeats validation at persistence.
        const checked = prevalidateReport(cwd, input.report, { formal, target: resolvedTarget });
        if (!checked.valid) {
          throw new Error('HX review preflight failed: ' + checked.issues.map(item =>
            `${item.path} [${item.code}]: ${item.message}`).join('; '));
        }
        payload.report = checked.report;
        const signed = JSON.stringify({
          payload: JSON.stringify(payload),
          signature: createHmac('sha256', attestationKey(directory)).update(JSON.stringify(payload)).digest('hex'),
        });
        const reports = formal ? join(cwd, '.hx', 'reports') : join(directory, 'review-inputs');
        mkdirSync(reports, { recursive: true, mode: 0o700 });
        const reference = createHash('sha256').update(`${context.sessionID}:${context.id}`).digest('hex').slice(0, 20);
        const target = join(reports, `${kind}.${reference}.signed.json`);
        writeFileSync(target, signed, { mode: 0o600 });
        const args = [...command, target, '--kind', kind];
        if (input.target && !formal) args.push('--target', resolvedTarget);
        if (input.base && !formal) args.push('--base', resolvedBase);
        const output = executeCli(cwd, args);
        return { content: JSON.stringify(output) };
      },
    });
  });
}
