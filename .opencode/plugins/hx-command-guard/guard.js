import { createHash } from 'node:crypto';

// Hash tool input for diagnostics without logging raw command arguments or secrets.
export function digestResources(resources) {
  return createHash('sha256').update(JSON.stringify(resources ?? null)).digest('hex');
}
