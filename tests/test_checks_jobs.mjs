import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { startChecks, checksStatus, workerLaunchOptions } from '../.opencode/plugins/hx-command-guard/checks-jobs.js';

async function completed(directory, cwd, id) {
  for (let i = 0; i < 80; i++) {
    const status = checksStatus(directory, cwd, id);
    if (!['RUNNING', 'QUEUED'].includes(status.status)) return status;
    await sleep(50);
  }
  throw new Error('Timeout waiting for detached checks worker');
}

test('background checks survive detached launch and report durable status', async () => {
  const root = mkdtempSync(join(tmpdir(), 'hx-check-job-'));
  try {
    const hxHome = join(root, 'hx');
    const directory = join(root, 'state');
    mkdirSync(hxHome);
    const script = `import json,sys,time\nfrom pathlib import Path\njob = sys.argv[sys.argv.index('--job-id')+1]\np = Path('state/check-jobs') / (job + '.json')\nd = json.loads(p.read_text())\nd['status'] = 'RUNNING'\np.write_text(json.dumps(d))\ntime.sleep(0.3)\nd['status'] = 'PASS'\np.write_text(json.dumps(d))\n`;
    writeFileSync(join(hxHome, 'checks_worker.py'), script);
    const preview = { sha256: 'abc', gates: [{ name: 'test', cwd: '.', argv: ['fake'] }] };
    const arguments_ = { directory, cwd: root, preview, pythonCommand: () => ['python3', []], hxHome };
    const started = await startChecks(arguments_);
    assert.equal(started.status, 'STARTED');
    const duplicate = await startChecks(arguments_);
    assert.equal(duplicate.already_running, true);
    assert.equal(duplicate.job_id, started.job_id);
    const result = await completed(directory, root, started.job_id);
    assert.equal(result.status, 'PASS');
    const newJob = await startChecks(arguments_);
    assert.notEqual(newJob.job_id, started.job_id);
    assert.equal((await completed(directory, root, newJob.job_id)).status, 'PASS');
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});


test('Windows checks worker prefers a GUI Python launcher to avoid console windows', () => {
  const root = mkdtempSync(join(tmpdir(), 'hx-windows-launch-'));
  try {
    const pyw = join(root, 'pyw.exe');
    const pythonw = join(root, 'pythonw.exe');
    writeFileSync(join(root, 'py.exe'), 'test');
    writeFileSync(join(root, 'python.exe'), 'test');
    writeFileSync(pyw, 'test');
    writeFileSync(pythonw, 'test');
    const fromPy = workerLaunchOptions(['py', ['-3']], { platform: 'win32', pathValue: root });
    assert.deepEqual(fromPy, { program: pyw, prefix: ['-3'], detached: true });
    const fromPython = workerLaunchOptions([join(root, 'python.exe'), []], { platform: 'win32' });
    assert.deepEqual(fromPython, { program: pythonw, prefix: [], detached: true });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('Windows console interpreters avoid detached mode when no GUI launcher exists', () => {
  const selected = workerLaunchOptions(['py', ['-3']], {
    platform: 'win32', pathValue: '', exists: () => false,
  });
  assert.deepEqual(selected, { program: 'py', prefix: ['-3'], detached: false });
  const arbitrary = workerLaunchOptions(['custom-python', []], { platform: 'win32' });
  assert.equal(arbitrary.detached, false);
});

test('Unix checks worker continues using detached sessions', () => {
  const selected = workerLaunchOptions(['python3', []], { platform: 'linux' });
  assert.deepEqual(selected, { program: 'python3', prefix: [], detached: true });
});


test('GUI Python selection is constrained to the selected console launcher directory', () => {
  const root = mkdtempSync(join(tmpdir(), 'hx-worker-dir-'));
  try {
    const other = join(root, 'other');
    const selected = join(root, 'selected');
    mkdirSync(other);
    mkdirSync(selected);
    writeFileSync(join(other, 'pyw.exe'), 'unrelated');
    writeFileSync(join(selected, 'py.exe'), 'selected');
    const command = workerLaunchOptions(['py', ['-3']], {
      platform: 'win32', pathValue: [other, selected].join(';'),
    });
    assert.deepEqual(command, { program: 'py', prefix: ['-3'], detached: false });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
