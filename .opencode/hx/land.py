"""Explicit, revision-bound landing of completed HX worktrees."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

from process_utils import run
import state


def git(cwd: Path, *args: str, input_data: bytes | None = None) -> str:
    result = run(["git", *args], cwd=cwd, input=input_data,
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return result.stdout.decode("utf-8", errors="replace").strip()


def changed_paths(cwd: Path) -> list[str]:
    return sorted(set(state.dirty_project_files(cwd)))


def source_digest(cwd: Path) -> str:
    """Hash eligible source content independently of the HX runtime version."""
    hasher = hashlib.sha256()
    head = git(cwd, "rev-parse", "HEAD")
    hasher.update(head.encode())
    for path in changed_paths(cwd):
        node = cwd / path
        if not node.resolve(strict=False).is_relative_to(cwd.resolve()):
            raise ValueError("Changed path escapes approved worktree: " + path)
        hasher.update(path.encode("utf-8") + b"\0")
        hasher.update(str(node.lstat().st_mode).encode() if node.exists() or node.is_symlink() else b"deleted-mode")
        if node.is_symlink():
            hasher.update(b"symlink:" + os.fsencode(os.readlink(node)))
        elif node.is_file():
            hasher.update(b"file:")
            with node.open("rb") as stream:
                for block in iter(lambda: stream.read(262144), b""):
                    hasher.update(block)
        else:
            hasher.update(b"deleted")
    return hasher.hexdigest()


def approved_task(cwd: Path, *, worktree_required: bool = True) -> dict:
    task = state.verify(cwd, ("COMPLETED",))
    if worktree_required and cwd.resolve() != Path(task["worktree"]).resolve():
        raise ValueError("Run HX land from the completed worktree")
    if task.get("checks") != "PASS" or task.get("review") != "APPROVED" or task.get("security") != "APPROVED":
        raise ValueError("HX landing requires PASS and two APPROVED reviews")
    if task.get("review_coverage") != "COMPLETE" or task.get("security_coverage") != "COMPLETE":
        raise ValueError("HX landing requires COMPLETE review coverage")
    revisions = [task.get(key) for key in ("checks_revision", "review_revision", "security_revision")]
    if not revisions[0] or len(set(revisions)) != 1:
        raise ValueError("HX landing requires all gates bound to one source revision")
    return task


def source_proof(cwd: Path, task: dict, legacy_override: bool = False) -> dict:
    expected = task.get("land_source_digest")
    actual = source_digest(cwd)
    if expected:
        if actual != expected:
            raise ValueError("Worktree source differs from completed HX snapshot; landing blocked")
        return {"status": "VERIFIED", "digest": actual}
    # Older versions did not record a runtime-independent source snapshot.
    if state.workspace_revision(cwd) == task["checks_revision"]:
        return {"status": "LEGACY_VERIFIED", "digest": actual}
    if legacy_override:
        return {"status": "LEGACY_MANUAL", "digest": actual}
    raise ValueError("Completed task predates land source snapshots and HX runtime changed; "
                     "cannot prove source matches approved reviews. Manually inspect and land via Git, "
                     "or revalidate the task with the original HX runtime.")


def branch(cwd: Path) -> str:
    return git(cwd, "branch", "--show-current")


def clean(cwd: Path) -> bool:
    """Ignore HX-owned tooling, but never ignore project changes."""
    return not changed_paths(cwd)


def main_checkout(task: dict) -> Path:
    root = Path(task["project_root"]).resolve()
    if not root.is_dir() or state.git_dir(root) != state.git_dir(Path(task["worktree"])):
        raise ValueError("Original repository checkout is unavailable")
    return root


def preview(cwd: Path, target_branch: str | None = None, strategy: str = "merge",
            legacy_override: bool = False) -> dict:
    task = approved_task(cwd)
    landing = task.get("landing") or {}
    if landing.get("status") in {"COMMITTED", "PR_PREPARED"}:
        return merge_preview(cwd, target_branch)
    if landing.get("status") in {"MERGED", "CLEANED"}:
        return {"phase": landing["status"], "task_id": task["id"], "landing": landing}
    if strategy not in ("merge", "pr"):
        raise ValueError("Landing strategy must be merge or pr")
    original = main_checkout(task)
    target = branch(original)
    if not target or (target_branch and target_branch != target):
        raise ValueError("Original checkout must be on the requested target branch")
    if not clean(original):
        raise ValueError("Original checkout is dirty; preserve its changes before landing")
    base = task.get("base_commit")
    current_target_head = git(original, "rev-parse", "HEAD")
    if strategy == "merge" and current_target_head != base:
        raise ValueError("Target branch advanced since HX approval; preview with strategy=pr to prepare a PR")
    if git(cwd, "rev-parse", "HEAD") != base:
        raise ValueError("Worktree HEAD changed since approval; cannot automatically land this revision")
    proof = source_proof(cwd, task, legacy_override)
    paths = changed_paths(cwd)
    if not paths:
        raise ValueError("No eligible source changes to commit")
    staged_protected = git(cwd, "diff", "--cached", "--name-only", "-z")
    if any(state.managed_hx_path(p) for p in staged_protected.split("\0") if p):
        raise ValueError("Staged HX-managed files must be unstaged before landing")
    source_branch = branch(cwd) or f"hx/{state.slug(task['title'])[:42]}-{task['id'][-8:]}"
    content = {
        "task_id": task["id"], "phase": "COMMIT", "target_branch": target,
        "target_head": current_target_head, "source_head": base, "source_branch": source_branch,
        "source_digest": proof["digest"], "files": paths, "strategy": strategy,
        "proof": proof["status"],
    }
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {**content, "manifest_sha256": digest, "phase": "PREVIEW", "proof": proof["status"],
            "file_count": len(paths), "diff_stat": git(cwd, "diff", "--stat", "HEAD"),
            "warning": ("LEGACY MANUAL: prior HX runtime changed; source cannot be cryptographically tied to prior approval. "
                        "User must review the complete diff and explicitly accept this limitation. "
                        if proof["status"] == "LEGACY_MANUAL" else "") +
                       ("This strategy prepares a PR draft, not a merge. No push." if strategy == "pr"
                        else "Commit stages only listed paths; Git hooks run normally. No push.")}


def commit(cwd: Path, expected_sha: str, target_branch: str | None = None, strategy: str = "merge",
           legacy_override: bool = False) -> dict:
    current = preview(cwd, target_branch, strategy, legacy_override)
    if current["phase"] != "PREVIEW" or current["manifest_sha256"] != expected_sha:
        raise ValueError("HX land preview changed; preview again and request new confirmation")
    task = approved_task(cwd)
    if not branch(cwd):
        git(cwd, "switch", "-c", current["source_branch"])
    paths = current["files"]
    indexed = set(filter(None, git(cwd, "ls-files", "--cached", "-z").split("\0")))
    # A staged rename can leave its old name absent from both index and disk.
    stageable = [path for path in paths if path in indexed or (cwd / path).exists() or (cwd / path).is_symlink()]
    if stageable:
        input_data = b"\0".join(os.fsencode(path) for path in stageable) + b"\0"
        # Stage an exact, reviewed path list; never stage HX internals or other files.
        git(cwd, "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul", input_data=input_data)
    if not git(cwd, "diff", "--cached", "--name-only"):
        raise ValueError("No staged source changes after Git add")
    tree = git(cwd, "write-tree")
    git(cwd, "commit", "-m", f"feat(hx): {task['title'][:60]}")
    commit_sha = git(cwd, "rev-parse", "HEAD")
    if git(cwd, "rev-parse", "HEAD^{tree}") != tree or changed_paths(cwd):
        raise ValueError("Commit hooks modified source or index; inspect manually before merging")
    with state.transaction(cwd):
        data, active = state.current(cwd)
        if active["id"] != task["id"] or active["status"] != "COMPLETED":
            raise ValueError("HX task state changed during commit")
        active["landing"] = {
            "status": "COMMITTED", "commit": commit_sha, "tree": tree,
            "source_branch": branch(cwd), "target_branch": current["target_branch"],
            "target_head": current["target_head"], "source_digest": current["source_digest"],
            "strategy": current["strategy"], "source_proof": current["proof"],
            "committed_at": state.timestamp(),
        }
        active["updated"] = state.timestamp()
        state.save(cwd, data)
    return {"phase": "COMMITTED", "commit": commit_sha, "branch": branch(cwd),
            "source_proof": current["proof"],
            "target_branch": current["target_branch"], "tree": tree,
            "note": "Commit created. Preview and confirm merge separately; no push performed."}


def merge_preview(cwd: Path, target_branch: str | None = None) -> dict:
    task = approved_task(cwd)
    landing = task.get("landing") or {}
    if landing.get("status") not in ("COMMITTED", "PR_PREPARED"):
        raise ValueError("Commit the completed source before requesting a merge")
    original = main_checkout(task)
    target = landing["target_branch"]
    if target_branch and target_branch != target:
        raise ValueError("Target branch differs from the committed landing plan")
    if branch(original) != target or not clean(original):
        raise ValueError("Original checkout must be clean and on the expected target branch")
    if git(original, "rev-parse", "HEAD") != landing["target_head"]:
        raise ValueError("Target branch advanced since the landing preview; prepare a PR instead")
    if git(cwd, "rev-parse", "HEAD") != landing["commit"] or not clean(cwd):
        raise ValueError("Source worktree changed since commit; merge blocked")
    if git(cwd, "rev-parse", "HEAD^{tree}") != landing["tree"]:
        raise ValueError("Committed tree changed; merge blocked")
    if landing["target_head"] != task["base_commit"]:
        return {"phase": "PR_READY", "task_id": task["id"],
                "source_commit": landing["commit"], "target_branch": target,
                "warning": "Target branch differs from approved base; only PR preparation is supported."}
    info = {
        "task_id": task["id"], "phase": "MERGE", "source": landing["commit"],
        "target_branch": target, "target_head": landing["target_head"], "tree": landing["tree"],
    }
    digest = hashlib.sha256(json.dumps(info, sort_keys=True).encode()).hexdigest()
    return {**info, "manifest_sha256": digest,
            "warning": "Merge creates a commit in the original checkout. No push or cleanup is performed."}


def merge(cwd: Path, expected_sha: str) -> dict:
    current = merge_preview(cwd)
    if current["phase"] != "MERGE" or current["manifest_sha256"] != expected_sha:
        raise ValueError("HX merge preview changed; preview again")
    task = approved_task(cwd)
    original = main_checkout(task)
    git(original, "merge", "--no-ff", "--no-edit", current["source"])
    merged = git(original, "rev-parse", "HEAD")
    if git(original, "rev-parse", "HEAD^{tree}") != current["tree"] or not clean(original):
        raise ValueError("Merged tree differs from reviewed code; inspect original checkout manually")
    with state.transaction(cwd):
        data, active = state.current(cwd)
        landing = active["landing"]
        if landing["commit"] != current["source"]:
            raise ValueError("Source commit changed while merging")
        landing.update({"status": "MERGED", "merge_commit": merged, "merged_at": state.timestamp()})
        active["updated"] = state.timestamp()
        state.save(cwd, data)
    return {"phase": "MERGED", "merge_commit": merged, "target_branch": current["target_branch"],
            "source_proof": landing["source_proof"],
            "source_commit": current["source"], "tree_verified": True,
            "note": "Merged locally. Nothing pushed; optional cleanup must be separately approved."}


def prepare_pr(cwd: Path) -> dict:
    task = approved_task(cwd)
    landing = task.get("landing") or {}
    if landing.get("status") != "COMMITTED":
        raise ValueError("PR preparation requires a committed HX worktree")
    source = landing["commit"]
    if git(cwd, "rev-parse", "HEAD") != source or not clean(cwd):
        raise ValueError("Source worktree changed since commit; PR draft blocked")
    if git(cwd, "rev-parse", "HEAD^{tree}") != landing["tree"]:
        raise ValueError("Committed source tree differs from reviewed landing tree")
    body = (f"# {task['title']}\n\n## HX validation\n"
            f"- Quality Gates: {task['checks']}\n"
            f"- Code review: {task['review']} ({task['review_coverage']})\n"
            f"- Security audit: {task['security']} ({task['security_coverage']})\n\n"
            f"## Changes\n{git(cwd, 'diff', '--stat', task['base_commit'], source)}\n\n"
            "## Manual review\nReview final source, deployment risks, and remote branch protection.\n")
    path = cwd / ".hx" / "PR.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    with state.transaction(cwd):
        data, active = state.current(cwd)
        active["landing"]["status"] = "PR_PREPARED"
        state.save(cwd, data)
    return {"phase": "PR_PREPARED", "path": str(path), "source_commit": source,
            "note": "Local PR draft only. No push and no remote PR created."}


def cleanup(cwd: Path) -> dict:
    task = approved_task(cwd, worktree_required=False)
    original = main_checkout(task)
    if cwd.resolve() != original:
        raise ValueError("Switch OpenCode to the original checkout before removing the worktree")
    landing = task.get("landing") or {}
    if landing.get("status") != "MERGED":
        raise ValueError("Only merged HX worktrees can be cleaned up automatically")
    worktree = Path(task["worktree"])
    if not clean(worktree):
        raise ValueError("Worktree has uncommitted changes; cleanup blocked")
    if git(original, "rev-parse", "HEAD") != landing["merge_commit"]:
        raise ValueError("Target checkout HEAD changed; inspect merge before cleanup")
    git(original, "worktree", "remove", str(worktree))
    with state.transaction(cwd):
        data, active = state.current(cwd)
        active["landing"].update({"status": "CLEANED", "cleaned_at": state.timestamp()})
        data.get("by_checkout", {}).pop(str(worktree.resolve()), None)
        state.save(cwd, data)
    return {"phase": "CLEANED", "worktree": str(worktree),
            "note": "Worktree removed without force. Source branch retained; no push."}
