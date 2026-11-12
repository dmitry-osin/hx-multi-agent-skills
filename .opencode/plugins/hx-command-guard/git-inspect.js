"use strict";

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

// Accept a SHA or HEAD with a single, bounded ancestry operator. Do not
// allow branch names, stacked expressions, paths, or Git option injection.
const REVISION = /^(?:[0-9a-fA-F]{7,40}|HEAD)(?:~(?:0|[1-9][0-9]{0,2})|\^(?:[1-9][0-9]{0,2})?)?$/;
const MAX_OUTPUT = 110000;

function git(cwd, args) {
  const output = execFileSync('git', ['--no-pager', ...args], {
    cwd, encoding: 'utf8', timeout: 20000,
    maxBuffer: 10 * 1024 * 1024, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    env: { ...process.env, GIT_PAGER: 'cat', GIT_EXTERNAL_DIFF: '', GIT_OPTIONAL_LOCKS: '0' },
  });
  return { output: output.slice(0, MAX_OUTPUT), truncated: output.length > MAX_OUTPUT };
}

function commit(cwd, input) {
  if (typeof input !== 'string' || !REVISION.test(input)) {
    throw new Error('HX Git: expected SHA or HEAD, optionally followed by ~N or ^N (N <= 999)');
  }
  const sha = git(cwd, ['rev-parse', '--verify', '--end-of-options', `${input}^{commit}`]).output.trim();
  if (!/^[0-9a-f]{40}$/.test(sha)) throw new Error('HX Git: cannot resolve commit');
  return sha;
}

function parents(cwd, sha) {
  // Resolve ancestry from the requested immutable SHA, never from moving HEAD.
  const tokens = git(cwd, ['rev-list', '--parents', '-n', '1', sha]).output.trim().split(/\s+/);
  if (tokens[0] !== sha || tokens.slice(1).some(value => !/^[0-9a-f]{40}$/.test(value))) {
    throw new Error('HX Git: could not determine the parents of the resolved commit');
  }
  return tokens.slice(1);
}

export function inspectGit(cwd, input) {
  switch (input.action) {
    case 'status':
      return { action: 'status', ...git(cwd, ['-c', 'core.quotePath=false', 'status', '--short']) };
    case 'working':
      return { action: 'working', ...git(cwd, ['diff', '--no-ext-diff', '--no-textconv', 'HEAD', '--']) };
    case 'commit': {
      const sha = commit(cwd, input.target);
      return { action: 'commit', sha, revision: sha, parents: parents(cwd, sha), ...git(cwd, ['show', '--no-ext-diff', '--no-textconv', '--no-renames', '--root', '--format=fuller', sha]) };
    }
    case 'range': {
      const base = commit(cwd, input.base);
      const target = commit(cwd, input.target);
      const revision = createHash('sha256').update(`${base}..${target}`).digest('hex');
      return { action: 'range', base, target, revision,
        ...git(cwd, ['diff', '--no-ext-diff', '--no-textconv', '--no-renames', base, target, '--']) };
    }
    case 'files': {
      const sha = commit(cwd, input.target);
      return { action: 'files', sha,
        ...git(cwd, ['diff-tree', '--root', '--no-commit-id', '--name-only', '-r', sha]) };
    }
    case 'file': {
      const sha = commit(cwd, input.target);
      const path = String(input.path ?? '');
      if (!path || path.includes('\\') || path.includes('..') || path.startsWith('/') ||
          path.includes('\0') || path.includes(':') || path.split('/').some(part => !part || part === '.')) {
        throw new Error('HX Git: file requires a safe relative repository path');
      }
      if (input.base !== undefined) {
        const base = commit(cwd, input.base);
        return { action: 'file', sha, base, path, contentType: 'diff',
          ...git(cwd, ['diff', '--no-ext-diff', '--no-textconv', '--no-renames', base, sha, '--', path]) };
      }
      return { action: 'file', sha, path, contentType: 'source', ...git(cwd, ['show', `${sha}:${path}`]) };
    }
    default:
      throw new Error('HX Git: unsupported read-only action');
  }
}
