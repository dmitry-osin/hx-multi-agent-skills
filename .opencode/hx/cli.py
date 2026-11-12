"""HX workflow CLI for local and global OpenCode installations."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import json
import shutil
import subprocess
from process_utils import run
import sys
from pathlib import Path

import gates
import state
import runtime
import standalone
import review_contract
import land


PRO_RATES = (0.66, 1.98)
FLASH_RATES = (0.15, 0.60)



def present(data: object) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def ensure_exclude(cwd: Path) -> None:
    exclude = state.git_dir(cwd) / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    current = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if "\n/.hx/\n" not in "\n" + current:
        exclude.write_text(current.rstrip("\n") + "\n/.hx/\n", encoding="utf-8")


def safe_copy(source: Path, target: Path, destination: Path) -> None:
    """Do not overwrite or follow adversarial worktree symlink targets."""
    if not target.is_relative_to(destination):
        raise ValueError("Copy target escapes worktree")
    node = target
    while node != destination:
        if node.is_symlink():
            raise ValueError(f"Unsafe worktree symlink: {node}")
        node = node.parent
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise ValueError(f"Refusing to overwrite existing worktree file: {target}")
    shutil.copy2(source, target)


def copy_bundle(cwd: Path, destination: Path) -> list[str]:
    if not destination.is_dir():
        raise ValueError("Worktree directory does not exist")
    copied = []
    if not runtime.local_install_for(cwd) and not (cwd / ".opencode" / "hx" / "cli.py").is_file():
        return copied
    manifest = ["opencode.jsonc", ".opencode/opencode.jsonc", ".opencode/opencode.json", ".opencode/hx", ".opencode/agents",
                ".opencode/commands", ".opencode/skills", ".opencode/plugins"]
    for name in manifest:
        origin = cwd / name
        target = destination / name
        if origin.is_dir():
            for file in origin.rglob("*"):
                if file.is_dir() or file.is_symlink() or any(part in ("__pycache__", "node_modules") for part in file.parts):
                    continue
                relative = file.relative_to(cwd)
                to = destination / relative
                safe_copy(file, to, destination)
                copied.append(relative.as_posix())
        elif origin.is_file():
            safe_copy(origin, target, destination)
            copied.append(name)
    return copied

def copy_plan(cwd: Path, destination: Path) -> None:
    draft = cwd / ".hx" / "plan.md"
    if draft.is_file():
        target = destination / ".hx" / "plan.md"
        safe_copy(draft, target, destination)


def attach(cwd: Path, target: Path) -> dict:
    task = state.verify(cwd, ("APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"))
    target = target.resolve()
    if target == cwd.resolve():
        raise ValueError("Worktree must differ from the original checkout")
    if state.git_dir(target) != state.git_dir(cwd):
        raise ValueError("Target must be a Git worktree of this repository")
    if git_output(target, "rev-parse", "HEAD") != task.get("base_commit"):
        raise ValueError("Worktree HEAD differs from the approved source commit")
    copied = copy_bundle(cwd, target)
    copy_plan(cwd, target)
    ensure_exclude(target)
    # Exclude only copied tooling; do not hide unrelated project configuration.
    if copied:
        exclude = state.git_dir(target) / "info" / "exclude"
        rules = exclude.read_text(encoding="utf-8")
        existing = set(rules.splitlines())
        for name in copied:
            entry = "/" + name
            if entry not in existing:
                rules += "\n" + entry
                existing.add(entry)
        exclude.write_text(rules.rstrip("\n") + "\n", encoding="utf-8")
    data, selected = state.current(cwd)
    selected["worktree"] = str(target)
    selected["updated"] = state.timestamp()
    data["by_checkout"][str(target)] = selected["id"]
    state.save(cwd, data)
    return selected


def ensure_location(cwd: Path, task: dict) -> None:
    path = task.get("worktree")
    if not path:
        raise ValueError("Create and attach a worktree before implementation")
    if cwd.resolve() != Path(path).resolve():
        raise ValueError("OpenCode session must run inside approved HX worktree")


def estimated_cost(records: list[dict]) -> float:
    total = 0.0
    for record in records:
        rate = PRO_RATES if record["model"] == "pro" else FLASH_RATES
        total += (record["input_tokens"] * rate[0] + record["output_tokens"] * rate[1]) / 1_000_000
    return total


def soft_budget(cwd: Path) -> float:
    path = runtime.project_override(cwd, "budget.json")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"soft_limit_usd": 5.0}
    return float(data["soft_limit_usd"])


def start(cwd: Path) -> dict:
    task = state.verify(cwd, ("APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED"))
    ensure_location(cwd, task)
    if estimated_cost(task.get("cost", [])) >= soft_budget(cwd):
        raise ValueError("HX recorded estimated cost reached soft budget; approve a higher budget manually")
    if task["status"] == "APPROVED":
        return state.change_status(cwd, "IMPLEMENTING")
    return task


def run_checks(cwd: Path, config: Path, expected_sha: str | None = None, host_approved: bool = False) -> dict:
    """Execute checks outside the global state lock and atomically record their result."""
    try:
        task = state.current(cwd)[1]
    except ValueError as exc:
        if "No active HX plan" not in str(exc):
            raise
        task = None
    formal = task is not None and task["status"] in ("IMPLEMENTING", "VERIFYING", "BLOCKED")
    if formal:
        state.verify(cwd, ("IMPLEMENTING", "VERIFYING", "BLOCKED"))
        ensure_location(cwd, task)
    task_id = task["id"] if formal else None
    outcome = gates.execute(cwd, config, expected_sha=expected_sha, host_approved=host_approved)
    if not formal:
        destination = state.state_dir(cwd) / "standalone-checks" / (outcome["manifest_sha256"] + ".json")
        state.write_json(destination, outcome)
        return {**outcome, "mode": "STANDALONE", "saved_to": str(destination),
                "notice": "Standalone checks do not approve or complete a formal HX task"}
    with state.transaction(cwd):
        active = state.current(cwd)[1]
        state.verify(cwd, ("IMPLEMENTING", "VERIFYING", "BLOCKED"))
        ensure_location(cwd, active)
        if active["id"] != task_id:
            raise ValueError("Active task changed while Quality Gates were running")
        if outcome["status"] == "PASS" and gates.manifest(cwd, config)["sha256"] != expected_sha:
            outcome["status"] = "FAIL"
            outcome["reason"] = "Workspace or manifest changed after checks finished"
        report = state.state_dir(cwd) / "reports" / task_id / "checks.json"
        state.write_json(report, outcome)
        state.add_event(cwd, "checks", outcome["status"])
        state.add_event(cwd, "checks_revision", state.workspace_revision(cwd))
        state.add_event(cwd, "checks_manifest_sha256", outcome["manifest_sha256"])
        state.change_status(cwd, "VERIFYING" if outcome["status"] == "PASS" else "BLOCKED")
    return outcome


def validate_review(cwd: Path, kind: str, signed: dict, task: dict) -> dict:
    """Validate both schema and plugin-recorded agent/session provenance."""
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ValueError("Install pinned Python dependency: pip install -r .opencode/hx/requirements.txt") from exc
    if not isinstance(signed, dict) or not isinstance(signed.get("payload"), str):
        raise ValueError("Review requires an attested report from hx_submit_review tool")
    signature = signed.get("signature", "")
    secret_path = state.state_dir(cwd) / "attest.key"
    if not secret_path.is_file():
        raise ValueError("No plugin attestation key: cannot accept review as verified")
    expected = hmac.new(secret_path.read_bytes(), signed["payload"].encode("utf-8"), hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid review agent attestation")
    payload = json.loads(signed["payload"])
    expected_agent = "reviewer" if kind == "review" else "security-auditor"
    if payload.get("agent") != expected_agent or not payload.get("session_id") or not payload.get("message_id"):
        raise ValueError("Review was not recorded from the required independent agent")
    if payload.get("task_id") != task["id"] or payload.get("workspace_revision") != state.workspace_revision(cwd):
        raise ValueError("Review attestation is for another task or stale revision")
    report = payload.get("report")
    report = review_contract.validate(cwd, report)
    return report


def review(cwd: Path, kind: str, report_file: Path) -> dict:
    task = state.verify(cwd, ("IMPLEMENTING", "VERIFYING", "BLOCKED"))
    ensure_location(cwd, task)
    if kind not in ("review", "security"):
        raise ValueError("Unknown review kind")
    signed = json.loads(report_file.read_text(encoding="utf-8"))
    report = validate_review(cwd, kind, signed, task)
    snapshot = state.state_dir(cwd) / "reports" / task["id"] / (kind + ".json")
    state.write_json(snapshot, {"report": report, "provenance": {
        "agent": "reviewer" if kind == "review" else "security-auditor",
        "attestation": "HX plugin session-bound HMAC; not external proof of correctness"}})
    state.add_event(cwd, kind, report["verdict"])
    state.add_event(cwd, kind + "_coverage", report["coverage"])
    return state.add_event(cwd, kind + "_revision", state.workspace_revision(cwd))


def next_round(cwd: Path) -> dict:
    data, task = state.current(cwd)
    state.verify(cwd, ("IMPLEMENTING", "BLOCKED", "VERIFYING"))
    ensure_location(cwd, task)
    if task.get("review") != "CHANGES_REQUESTED" and task.get("security") != "CHANGES_REQUESTED" and task.get("checks") != "FAIL":
        raise ValueError("No recorded failed gate or requested changes")
    if task["round"] >= 2:
        raise ValueError("Correction limit reached: request a new plan/reapproval")
    task["round"] += 1
    task["status"] = "IMPLEMENTING"
    task["checks"] = None
    task["review"] = None
    task["security"] = None
    task["review_coverage"] = None
    task["security_coverage"] = None
    task["checks_revision"] = None
    task["review_revision"] = None
    task["security_revision"] = None
    task["updated"] = state.timestamp()
    state.save(cwd, data)
    return task


def can_complete(cwd: Path) -> dict:
    task = state.verify(cwd, ("VERIFYING", "BLOCKED"))
    ensure_location(cwd, task)
    missing = [label for label in ("checks", "review", "security") if task.get(label) != "PASS" and task.get(label) != "APPROVED"]
    if missing:
        raise ValueError("Cannot complete; unapproved gates: " + ", ".join(missing))
    incomplete = [label for label in ("review", "security") if task.get(label + "_coverage") != "COMPLETE"]
    if incomplete:
        raise ValueError("Cannot complete; review coverage is not COMPLETE: " + ", ".join(incomplete))
    revision = state.workspace_revision(cwd)
    stale = [key for key in ("checks_revision", "review_revision", "security_revision")
             if task.get(key) != revision]
    if stale:
        raise ValueError("Source changed after checks or reviews: " + ", ".join(stale))
    task = state.change_status(cwd, "COMPLETED")
    task["land_source_digest"] = land.source_digest(cwd)
    data, active = state.current(cwd)
    active["land_source_digest"] = task["land_source_digest"]
    state.save(cwd, data)
    return active


def git_output(cwd: Path, *args: str) -> str:
    result = run(["git", *args], cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout.strip()


def diff(cwd: Path, target: str | None = None) -> dict:
    if target:
        sha = standalone.resolve_commit(cwd, target)
        return {"mode": "STANDALONE", "target": sha,
                "commit": git_output(cwd, "show", "--no-ext-diff", "--no-textconv", "--format=fuller", "--stat", sha),
                "patch": git_output(cwd, "show", "--no-ext-diff", "--no-textconv", "--format=", "--root", sha)[:120000]}
    try:
        task = state.current(cwd)[1]
    except ValueError as exc:
        if "No active HX plan" not in str(exc):
            raise
        task = None
    if task and task["status"] in ("APPROVED", "IMPLEMENTING", "VERIFYING", "BLOCKED", "COMPLETED"):
        state.verify(cwd)
        ensure_location(cwd, task)
    return {
        "mode": "HX" if task else "STANDALONE",
        "branch": git_output(cwd, "branch", "--show-current"),
        "stat": git_output(cwd, "diff", "--stat", "HEAD"),
        "files": git_output(cwd, "status", "--short"),
        "note": "Untracked files are shown in files, but not included in git diff --stat HEAD",
    }


def pr(cwd: Path) -> dict:
    try:
        task = state.current(cwd)[1]
    except ValueError as exc:
        if "No active HX plan" not in str(exc):
            raise
        task = None
    if not task or task["status"] != "COMPLETED":
        text = ("# Standalone change summary\n\n## Validation\nUNVERIFIED — no HX plan or quality gates are attested.\n\n"
                "## Changes\n" + git_output(cwd, "diff", "--stat", "HEAD") + "\n\n"
                "## Manual QA / risks\nFill in test evidence and review findings manually.\n")
        target = cwd / ".hx" / "PR.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return {"path": str(target), "mode": "STANDALONE", "validation": "UNVERIFIED",
                "note": "Local draft only; no remote PR or Git mutation created"}
    state.verify(cwd, ("COMPLETED",))
    ensure_location(cwd, task)
    text = (f"# {task['title']}\n\n## Approved plan\n"
            f"{task['id']} v{task['version']} ({task['sha256'][:12]})\n\n"
            f"## Validation\n- Quality gates: {task['checks']}\n"
            f"- Code review: {task['review']}\n- Security audit: {task['security']}\n\n"
            "## Changes\n" + git_output(cwd, "diff", "--stat", "HEAD") + "\n\n"
            "## Manual QA / risks\n- Fill from approved plan and review reports.\n")
    target = cwd / ".hx" / "PR.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return {"path": str(target), "note": "PR draft only; no commit, push, or remote PR created"}


def cost(cwd: Path, model: str | None, input_tokens: int, output_tokens: int) -> dict:
    try:
        data, task = state.current(cwd)
    except ValueError as exc:
        if "No active HX plan" not in str(exc):
            raise
        return {"mode": "STANDALONE", "estimated_usd": None,
                "recorded_tokens_only": True, "records": [],
                "warning": "No HX records. For actual OpenCode usage run opencode stats --cost separately; this tool does not access DeepSeek billing."}
    if model:
        if model not in ("pro", "flash"):
            raise ValueError("model must be pro or flash")
        if min(input_tokens, output_tokens) < 0:
            raise ValueError("Token counts must be non-negative")
        task["cost"].append({"model": model, "input_tokens": input_tokens, "output_tokens": output_tokens})
        state.save(cwd, data)
    total = estimated_cost(task.get("cost", []))
    return {"estimated_usd": round(total, 6) if task.get("cost") else None,
            "soft_limit_usd": soft_budget(cwd),
            "recorded_tokens_only": True, "records": task.get("cost", []),
            "warning": "MANUAL tokens only; not automatically synchronized with DeepSeek billing."
                       " Prices are examples for direct API, verify live pricing."}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HX workflow controls")
    parser.add_argument("command", choices=("submit", "approve-preflight", "approve", "verify", "status", "attach", "start", "checks-preview", "checks", "review", "cycle", "complete", "diff", "pr", "cost", "revision", "standalone-review", "review-validate", "land-preview", "land-commit", "land-merge", "land-pr", "land-cleanup"))
    parser.add_argument("argument", nargs="?")
    parser.add_argument("--kind", choices=("review", "security"), default="review")
    parser.add_argument("--base", help="Base commit SHA for standalone ranges")
    parser.add_argument("--target", help="Optional hexadecimal commit SHA for independent review")
    parser.add_argument("--formal", action="store_true", help="Validate report against active worktree")
    parser.add_argument("--model", choices=("pro", "flash"))
    parser.add_argument("--task-id", help="Explicit task UUID-suffixed ID")
    parser.add_argument("--manifest-sha", help="Exactly previewed Quality Gates manifest SHA-256")
    parser.add_argument("--host-approved", action="store_true", help="User approved host build risks through OpenCode permission")
    parser.add_argument("--land-sha", help="Exact HX land preview digest")
    parser.add_argument("--land-target", help="Target branch for HX landing")
    parser.add_argument("--land-strategy", choices=("merge", "pr"), default="merge")
    parser.add_argument("--land-legacy-override", action="store_true")
    parser.add_argument("--human-confirm", help="Exact task-id:sha12 after interactive human approval")
    parser.add_argument("--input-tokens", type=int, default=0)
    parser.add_argument("--output-tokens", type=int, default=0)
    return parser.parse_args()


def current_status(cwd: Path) -> dict:
    try:
        task = state.current(cwd)[1]
    except ValueError as exc:
        if "No active HX plan" not in str(exc):
            raise
        return {"status": "NO_TASK", "mode": "STANDALONE", "message": "No registered HX task in this checkout"}
    if task["status"] == "DRAFT":
        return task
    try:
        state.verify(cwd)
        return {**task, "integrity": "VALID"}
    except ValueError as exc:
        return {**task, "integrity": "INVALID", "error": str(exc)}


def dispatch(cwd: Path, args: argparse.Namespace) -> object:
    def approve_interactively() -> dict:
        task = state.current(cwd, args.task_id)[1]
        code = f"{task['id']}:{task['sha256'][:12]}"
        if not args.human_confirm or args.human_confirm != code:
            raise ValueError(f"Approval requires exact plan identifier {code} and explicit user confirmation")
        if os.environ.get("HX_PLUGIN_APPROVED") != "1":
            if not sys.stdin.isatty():
                raise ValueError("Approval requires a human terminal or HX plugin permission prompt")
            answer = input(f"Approve plan {code}? Type APPROVE: ")
            if answer != "APPROVE":
                raise ValueError("Approval rejected")
        return state.approve(cwd, args.task_id)

    state.SELECTED_TASK_ID = args.task_id
    handlers = {
        "submit": lambda: state.register(cwd, args.task_id),
        "approve-preflight": lambda: state.preflight_approval(cwd, args.task_id),
        "approve": approve_interactively,
        "verify": lambda: state.verify(cwd),
        "status": lambda: current_status(cwd),
        "attach": lambda: attach(cwd, Path(args.argument or "")),
        "start": lambda: start(cwd),
        "checks-preview": lambda: gates.manifest(cwd, runtime.project_override(cwd, "quality-gates.json")),
        "checks": lambda: run_checks(cwd, runtime.project_override(cwd, "quality-gates.json"), args.manifest_sha, args.host_approved),
        "review": lambda: review(cwd, args.kind, Path(args.argument or "")),
        "cycle": lambda: next_round(cwd),
        "complete": lambda: can_complete(cwd),
        "diff": lambda: diff(cwd, args.argument),
        "pr": lambda: pr(cwd),
        "cost": lambda: cost(cwd, args.model, args.input_tokens, args.output_tokens),
        "revision": lambda: {"sha256": state.workspace_revision(cwd),
                            "task_id": current_status(cwd).get("id")},
        "standalone-review": lambda: standalone.record(cwd, Path(args.argument or ""), args.kind, args.target, args.base),
        "land-preview": lambda: land.preview(cwd, args.land_target, args.land_strategy, args.land_legacy_override),
        "land-commit": lambda: land.commit(cwd, args.land_sha or "", args.land_target, args.land_strategy, args.land_legacy_override),
        "land-merge": lambda: land.merge(cwd, args.land_sha or ""),
        "land-pr": lambda: land.prepare_pr(cwd),
        "land-cleanup": lambda: land.cleanup(cwd),
        "review-validate": lambda: review_contract.preflight(
            cwd, json.loads(sys.stdin.read()),
            commit=(standalone.resolve_commit(cwd, args.target) if args.target and not args.formal else None)),
    }
    return handlers[args.command]()

def main() -> int:
    try:
        args = parse_args()
        cwd = Path.cwd()
        if args.command in ("checks", "land-preview", "land-commit", "land-merge", "land-pr", "land-cleanup"):
            present(dispatch(cwd, args))
        else:
            with state.transaction(cwd):
                present(dispatch(cwd, args))
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr) or detail
        result = {"error": detail.strip(), "status": "BLOCKED"}
        if isinstance(exc, review_contract.ReviewValidationError):
            result["issues"] = exc.issues
        present(result)
        return 2


if __name__ == "__main__":
    sys.exit(main())
