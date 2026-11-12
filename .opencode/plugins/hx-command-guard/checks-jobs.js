"use strict";

import { randomUUID, createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { closeSync, existsSync, mkdirSync, openSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, resolve } from 'node:path';

const ACTIVE = new Set(['QUEUED', 'RUNNING']);
const TERMINAL = new Set(['PASS', 'FAIL', 'UNVERIFIED', 'ERROR']);

function activePointer(directory, cwd) {
  const key = createHash('sha256').update(resolve(cwd)).digest('hex').slice(0, 20);
  return join(directory, 'check-jobs', `active.${key}.json`);
}

function jobFile(directory, id) {
  if (!/^[a-f0-9-]{36}$/i.test(id)) throw new Error('Invalid HX Quality Gate job ID');
  return join(directory, 'check-jobs', `${id}.json`);
}

function readJson(file) {
  return JSON.parse(readFileSync(file, 'utf8'));
}

function saveJson(file, data) {
  writeFileSync(file, JSON.stringify(data, null, 2) + '\n', { mode: 0o600 });
}

function readCurrent(directory, cwd, id) {
  const folder = join(directory, 'check-jobs');
  const pointer = activePointer(directory, cwd);
  if (!id && !existsSync(pointer)) return { status: 'NO_JOB', message: 'No HX checks have been started' };
  const name = id ?? readJson(pointer).id;
  const file = jobFile(directory, name);
  if (!existsSync(file)) return { status: 'NO_JOB', job_id: name };
  const data = readJson(file);
  if (resolve(data.cwd) !== resolve(cwd)) {
    return { status: 'NO_JOB', message: 'Latest HX checks belong to another worktree; supply its cwd' };
  }
  if (ACTIVE.has(data.status)) {
    const elapsed = Date.now() - Date.parse(data.updated_at ?? data.created_at);
    if (elapsed > 120000 && !Number.isInteger(data.pid)) {
      return { ...data, status: 'UNVERIFIED', reason: 'Checks worker did not report a process ID; inspect its log before restarting' };
    }
    if (elapsed > 120000 && Number.isInteger(data.pid)) {
      try { process.kill(data.pid, 0); }
      catch (error) {
        if (error.code === 'ESRCH') {
          return { ...data, status: 'UNVERIFIED', reason: 'Detached worker process is no longer running; no PASS was recorded' };
        }
      }
    }
    if (elapsed > 15 * 60 * 1000) {
      return { ...data, warning: 'Checks have been active for over 15 minutes; inspect their log before retrying' };
    }
  }
  return data;
}

export function checksStatus(directory, cwd, id) {
  return readCurrent(directory, cwd, id);
}

function prepareJob(directory, cwd, preview) {
  const folder = join(directory, 'check-jobs');
  mkdirSync(folder, { recursive: true, mode: 0o700 });
  const latest = readCurrent(directory, cwd);
  if (ACTIVE.has(latest.status)) return { existing: latest };
  const id = randomUUID();
  const job = {
    job_id: id, cwd, status: 'QUEUED', created_at: new Date().toISOString(),
    manifest_sha256: preview.sha256, gates: preview.gates.map(g => ({ name: g.name, cwd: g.cwd, argv: g.argv })),
  };
  saveJson(jobFile(directory, id), job);
  saveJson(activePointer(directory, cwd), { id, cwd });
  return { job };
}

/** Select a console-free worker launcher without changing the Python version. */
export function workerLaunchOptions(python, options = {}) {
  const platform = options.platform ?? process.platform;
  const [program, prefix] = python;
  if (platform !== 'win32') return { program, prefix, detached: true };

  const executable = basename(program).replace(/\.exe$/i, '').toLowerCase();
  const guiName = executable === 'py' ? 'pyw.exe'
    : ['python', 'python3'].includes(executable) ? 'pythonw.exe' : null;
  if (guiName) {
    const pathValue = options.pathValue ?? process.env.PATH ?? '';
    const hasDirectory = /[\\/]/.test(program);
    const directories = hasDirectory ? [dirname(program)] : pathValue.split(';').filter(Boolean);
    const exists = options.exists ?? existsSync;
    const guiPath = directories
      .filter(directory => hasDirectory || exists(join(directory, `${executable}.exe`)))
      .map(directory => join(directory, guiName)).find(exists);
    if (guiPath) return { program: guiPath, prefix, detached: true };
  }

  // Windows detached console apps may create a new visible console window.
  return { program, prefix, detached: false };
}

export async function startChecks({ directory, cwd, preview, pythonCommand, hxHome }) {
  const { program, prefix, detached } = workerLaunchOptions(pythonCommand());
  const prepared = prepareJob(directory, cwd, preview);
  if (prepared.existing) return { ...prepared.existing, already_running: true };
  const { job } = prepared;
  const script = join(hxHome, 'checks_worker.py');
  const args = [...prefix, script, '--job-id', job.job_id, '--manifest-sha', preview.sha256];
  const logPath = join(directory, 'check-jobs', `${job.job_id}.log`);
  let fd;
  try { fd = openSync(logPath, 'a', 0o600); }
  catch (error) {
    saveJson(jobFile(directory, job.job_id), { ...job, status: 'ERROR', error: error.message });
    throw error;
  }
  let child;
  try {
    child = spawn(program, args, {
      cwd, env: process.env, detached, windowsHide: true,
      stdio: ['ignore', fd, fd],
    });
  } catch (error) {
    saveJson(jobFile(directory, job.job_id), { ...job, status: 'ERROR', error: error.message });
    throw error;
  } finally {
    closeSync(fd);
  }
  try {
    await new Promise((resolveStart, rejectStart) => {
      child.once('spawn', resolveStart);
      child.once('error', rejectStart);
    });
  } catch (error) {
    saveJson(jobFile(directory, job.job_id), { ...job, status: 'ERROR', error: error.message });
    throw new Error(`Failed to start HX checks worker: ${error.message}`);
  }
  child.unref();
  return { ...job, status: 'STARTED', pid: child.pid,
    log_path: logPath,
    message: 'Quality Gates are running independently. Poll hx_checks_status; do not complete before PASS.' };
}

export const checkStatusIsTerminal = status => TERMINAL.has(status);
