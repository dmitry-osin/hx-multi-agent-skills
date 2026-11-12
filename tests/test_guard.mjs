import test from 'node:test';
import assert from 'node:assert/strict';
import { digestResources } from '../.opencode/plugins/hx-command-guard/guard.js';

test('HX tool telemetry hashes resources instead of storing secrets', () => {
  const token = 'test-secret-only';
  const digest = digestResources([token]);
  assert.match(digest, /^[a-f0-9]{64}$/);
  assert.ok(!digest.includes(token));
  assert.equal(digest, digestResources([token]));
});

test('HX no longer exports a shell permission classifier or sandbox command rewriter', async () => {
  const module = await import('../.opencode/plugins/hx-command-guard/guard.js');
  assert.deepEqual(Object.keys(module), ['digestResources']);
});
