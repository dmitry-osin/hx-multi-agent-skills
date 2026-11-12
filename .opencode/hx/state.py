"""Persistent state and approval checks for HX workflows."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from contextlib import contextmanager
import json
import re
import unicodedata
import subprocess
from process_utils import run
from datetime import datetime, timezone
from pathlib import Path

import runtime

@contextmanager
def transaction(cwd: Path):
    """Serialize CLI state transitions across independent processes."""
    lockfile = state_dir(cwd) / "state.lock"
    lockfile.parent.mkdir(parents=True, exist_ok=True)
    with lockfile.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)




SELECTED_TASK_ID: str | None = None

HEADINGS = (
    "scope",
    "tasks",
    "acceptance criteria",
    "quality gates",
    "security",
    "documentation",
    "risks",
)


def git_dir(cwd: Path) -> Path:
    result = run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=cwd, text=True, capture_output=True, check=True,
    )
    return (cwd / result.stdout.strip()).resolve()


def state_dir(cwd: Path) -> Path:
    return git_dir(cwd) / "hx"


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text).casefold()
    result = re.sub(r"[^\w]+", "-", normalized, flags=re.UNICODE).strip("-")
    return result[:55] or "work-item"


def load(cwd: Path) -> dict:
    path = state_dir(cwd) / "state.json"
    if not path.exists():
        return {"current": None, "tasks": {}, "by_checkout": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("by_checkout", {})
    return data


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)
    if os.name != "nt":
        path.chmod(0o600)


def save(cwd: Path, data: dict) -> None:
    write_json(state_dir(cwd) / "state.json", data)


def current(cwd: Path, task_id: str | None = None) -> tuple[dict, dict]:
    data = load(cwd)
    selected = task_id or SELECTED_TASK_ID or data["by_checkout"].get(str(cwd.resolve())) or data.get("current")
    if not selected or selected not in data["tasks"]:
        raise ValueError("No active HX plan; run /hx-plan first or specify --task-id")
    task = data["tasks"][selected]
    bound = task.get("worktree")
    root = task.get("project_root")
    if str(cwd.resolve()) not in (bound, root):
        raise ValueError("Task is not associated with this checkout")
    return data, task


def validate_plan(content: str) -> None:
    headings = set(re.findall(r"^##\s+(.+?)\s*$", content, re.MULTILINE | re.IGNORECASE))
    missing = [heading for heading in HEADINGS if heading not in {item.lower() for item in headings}]
    if missing:
        raise ValueError("Plan lacks required headings: " + ", ".join(missing))
    if len(content.strip()) < 250:
        raise ValueError("Plan is too short: include actionable tasks and acceptance criteria")


def register(cwd: Path, task_id: str | None = None) -> dict:
    exclude = git_dir(cwd) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if "/.hx/" not in existing.splitlines():
        exclude.write_text(existing.rstrip("\n") + "\n/.hx/\n", encoding="utf-8")
    source = cwd / ".hx" / "plan.md"
    if not source.is_file():
        raise ValueError("Write .hx/plan.md first; only plan artifacts may change in plan mode")
    content = source.read_text(encoding="utf-8")
    validate_plan(content)
    name = next((line[2:].strip() for line in content.splitlines() if line.startswith("# ")), "Work item")
    data = load(cwd)
    active = data["tasks"].get(task_id or data["by_checkout"].get(str(cwd.resolve()), ""))
    prev = active if active and active["title"] == name and active["project_root"] == str(cwd.resolve()) else None
    if task_id is not None and prev is None:
        raise ValueError("Requested task does not match this plan/checkout")
    task_id = prev["id"] if prev else f"{slug(name)}-{uuid.uuid4().hex[:12]}"
    digest = fingerprint(content)
    if prev and prev["sha256"] == digest:
        data["current"] = task_id
        data["by_checkout"][str(cwd.resolve())] = task_id
        save(cwd, data)
        return prev
    version = prev["version"] + 1 if prev else 1
    history = state_dir(cwd) / "plans" / task_id / f"v{version:03}.md"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(content, encoding="utf-8")
    if os.name != "nt":
        history.chmod(0o600)
    task = {
        "id": task_id, "title": name, "version": version, "project_root": str(cwd.resolve()),
        "sha256": digest, "status": "DRAFT", "updated": timestamp(),
        "worktree": None, "checks": None, "review": None,
        "security": None, "round": 0, "cost": [],
    }
    data["current"] = task_id
    data["by_checkout"][str(cwd.resolve())] = task_id
    data["tasks"][task_id] = task
    save(cwd, data)
    return task


def verify(cwd: Path, accepted: tuple[str, ...] = ("APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "COMPLETED"), task_id: str | None = None) -> dict:
    _, task = current(cwd, task_id)
    if task["status"] not in accepted:
        raise ValueError(f"Plan status {task['status']}; run /hx-approve")
    snapshot = state_dir(cwd) / "plans" / task["id"] / f"v{task['version']:03}.md"
    content = snapshot.read_text(encoding="utf-8")
    if fingerprint(content) != task["sha256"]:
        raise ValueError("Approved plan snapshot was modified; approval invalid")
    roots = (cwd, Path(task.get("project_root", str(cwd))))
    for root in roots:
        local_plan = root / ".hx" / "plan.md"
        if local_plan.exists() and fingerprint(local_plan.read_text(encoding="utf-8")) != task["sha256"]:
            raise ValueError("Local plan has changed; submit and reapprove it")
    return task


def managed_hx_path(path: str) -> bool:
    agent_names = {"architect", "orchestrator", "developer", "test-engineer",
                   "documentation", "reviewer", "security-auditor"}
    if path.startswith(".hx/") or path.startswith(".opencode/hx/") or path.startswith(".opencode/plugins/hx-command-guard/"):
        return True
    if path.startswith(".opencode/commands/hx-") and path.endswith(".md"):
        return True
    if path.startswith(".opencode/skills/hx-"):
        return True
    if path.startswith(".opencode/agents/"):
        return Path(path).stem in agent_names
    return path in ("opencode.jsonc", "opencode.json", ".opencode/opencode.jsonc", ".opencode/opencode.json")


def dirty_project_files(cwd: Path) -> list[str]:
    """Parse Git porcelain -z without mangling renames or UTF-8 paths."""
    result = run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=cwd, capture_output=True, check=True,
    )
    entries = result.stdout.split(b"\0")
    files = []
    index = 0
    while index < len(entries):
        item = entries[index]
        index += 1
        if not item:
            continue
        status = item[:2].decode("ascii", errors="replace")
        name = os.fsdecode(item[3:])
        paths = [name]
        if "R" in status or "C" in status:
            if index < len(entries):
                paths.append(os.fsdecode(entries[index]))
                index += 1
        files.extend(path for path in paths if path and not managed_hx_path(path))
    return files


def preflight_approval(cwd: Path, task_id: str | None = None) -> dict:
    """Validate all known approval preconditions before asking the user.

    Approval repeats these checks after the permission prompt to prevent races.
    """
    _, task = current(cwd, task_id)
    if task["status"] != "DRAFT":
        raise ValueError("Only a DRAFT plan can be approved")
    source = cwd / ".hx" / "plan.md"
    if not source.is_file() or fingerprint(source.read_text(encoding="utf-8")) != task["sha256"]:
        raise ValueError("Draft changed after registration; resubmit /hx-plan")
    snapshot = state_dir(cwd) / "plans" / task["id"] / f"v{task['version']:03}.md"
    if not snapshot.is_file() or fingerprint(snapshot.read_text(encoding="utf-8")) != task["sha256"]:
        raise ValueError("Registered snapshot is missing or has been altered")
    changes = dirty_project_files(cwd)
    if changes:
        raise ValueError("Source checkout has uncommitted changes missing from new worktree: " + ", ".join(changes[:8]))
    return {"id": task["id"], "title": task["title"], "version": task["version"],
            "sha256": task["sha256"], "status": task["status"]}


def approve(cwd: Path, task_id: str | None = None) -> dict:
    preflight_approval(cwd, task_id)
    data, task = current(cwd, task_id)
    head = run(
        ["git", "rev-parse", "HEAD"], cwd=cwd,
        text=True, capture_output=True, check=True,
    ).stdout.strip()
    task["base_commit"] = head
    task["status"] = "APPROVED"
    task["approved_at"] = timestamp()
    task["updated"] = timestamp()
    save(cwd, data)
    return task


def workspace_revision(cwd: Path) -> str:
    """Bind every QA result to HEAD, index and eligible on-disk files."""
    digest = hashlib.sha256()
    for command in (["git", "rev-parse", "HEAD"], ["git", "write-tree"]):
        data = run(command, cwd=cwd, capture_output=True, check=True).stdout
        digest.update(data)
    listed = run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=cwd, capture_output=True, check=True,
    ).stdout
    extra = [b"opencode.jsonc"] if (cwd / "opencode.jsonc").exists() else []
    local_hx = cwd / ".opencode"
    if local_hx.is_dir():
        extra.extend(os.fsencode(str(path.relative_to(cwd))) for path in local_hx.rglob("*") if path.is_file())
    for raw in sorted(set(filter(None, listed.split(b"\0"))) | set(extra)):
        name = os.fsdecode(raw)
        path = Path(name)
        if path.parts and path.parts[0] == ".hx":
            continue
        if "node_modules" in path.parts or "__pycache__" in path.parts or ".pytest_cache" in path.parts:
            continue
        source = cwd / path
        digest.update(raw + b"\0")
        if source.is_symlink():
            digest.update(b"symlink:" + os.fsencode(os.readlink(source)))
        elif source.is_file():
            info = source.lstat()
            digest.update(str(stat.S_IMODE(info.st_mode)).encode())
            with source.open("rb") as stream:
                for block in iter(lambda: stream.read(262144), b""):
                    digest.update(block)
        else:
            digest.update(b"missing")
    # Global HX files are not part of the Git checkout. Bind verification to
    # the active agent/runtime installation as well as the project revision.
    hx_home = runtime.HX_HOME
    global_root = hx_home.parent
    if not runtime.local_install_for(cwd) and not (cwd / ".opencode" / "hx" / "cli.py").is_file():
        roots = [hx_home, global_root / "plugins" / "hx-command-guard",
                 global_root / "agents", global_root / "commands", global_root / "skills"]
        for root in roots:
            if not root.is_dir():
                continue
            for file in sorted(root.rglob("*")):
                if not file.is_file() or file.is_symlink() or any(
                    part in ("__pycache__", "node_modules", ".pytest_cache") for part in file.parts
                ):
                    continue
                digest.update(str(file.relative_to(global_root)).encode("utf-8") + b"\0")
                digest.update(hashlib.sha256(file.read_bytes()).digest())
        global_config = global_root / "opencode.jsonc"
        if global_config.is_file():
            digest.update(hashlib.sha256(global_config.read_bytes()).digest())
    return digest.hexdigest()


def change_status(cwd: Path, status: str) -> dict:
    data, task = current(cwd)
    task["status"] = status
    task["updated"] = timestamp()
    save(cwd, data)
    return task


def add_event(cwd: Path, key: str, value: object) -> dict:
    data, task = current(cwd)
    task[key] = value
    task["updated"] = timestamp()
    save(cwd, data)
    return task
