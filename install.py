#!/usr/bin/env python3
"""Install HX globally or into one Git project without silently overwriting user files."""

from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from datetime import datetime, timezone

SOURCE = Path(__file__).resolve().parent
IGNORE_PARTS = {"__pycache__", ".pytest_cache", "node_modules"}
# Retired HX-specific roles. A generic root.md is only removed if it contains an HX marker.
RETIRED_HX_FILES = (
    "agents/hx-quick-fix.md",
    "commands/hx-quick-fix.md",
    "agents/hx-root.md",
    "commands/hx-root.md",
    "agents/root.md",
)


def retired_hx_files(target_root: Path) -> list[Path]:
    """Find retired HX files without deleting an unrelated user-owned root agent."""
    result = []
    for relative in RETIRED_HX_FILES:
        path = target_root / relative
        if not path.is_file() or path.is_symlink():
            continue
        if relative == "agents/root.md":
            content = path.read_text(encoding="utf-8", errors="replace").lower()
            if not any(marker in content for marker in ("hx-root", "hx root", "hx quick fix")):
                continue
        result.append(path)
    return result



def strip_jsonc(source: str) -> str:
    """Remove JSONC comments and trailing commas while preserving JSON strings."""
    output: list[str] = []
    index = 0
    quoted = False
    escaped = False
    while index < len(source):
        char = source[index]
        if quoted:
            output.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            index += 1
            continue
        if char == '"':
            quoted = True
            output.append(char)
            index += 1
            continue
        if source.startswith("//", index):
            while index < len(source) and source[index] != "\n":
                index += 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end < 0:
                raise ValueError("Unterminated JSONC block comment")
            index = end + 2
            continue
        output.append(char)
        index += 1
    without_comments = "".join(output)
    result: list[str] = []
    quoted = False
    escaped = False
    for index, char in enumerate(without_comments):
        if quoted:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        if char == ",":
            lookahead = index + 1
            while lookahead < len(without_comments) and without_comments[lookahead].isspace():
                lookahead += 1
            if lookahead < len(without_comments) and without_comments[lookahead] in "]}":
                continue
        result.append(char)
    return "".join(result)


def load_config(path: Path) -> dict:
    result = json.loads(strip_jsonc(path.read_text(encoding="utf-8")))
    if not isinstance(result, dict):
        raise ValueError(f"OpenCode config is not an object: {path}")
    return result


# Exact rules shipped by the previous HX bundle. A migration removes only these
# matching entries from a detected older HX installation; other rules are retained.
LEGACY_PERMISSIONS = (
    ("shell", "*", "ask"),
    ("external_directory", "*", "ask"),
    ("read", "*.env", "deny"),
    ("read", "*.env.*", "deny"),
    ("read", "*.env.example", "allow"),
    ("hx_submit_review", "*", "allow"),
    ("hx_git_inspect", "*", "allow"),
)
LEGACY_POLICIES = (
    ("tool.use", "shell:*hx/cli.py approve*", "deny"),
    ("tool.use", "edit:.opencode/hx/**", "deny"),
    ("tool.use", "edit:.opencode/agents/**", "deny"),
    ("tool.use", "edit:opencode.jsonc", "deny"),
    ("tool.use", "edit:.opencode/opencode.json*", "deny"),
    ("tool.use", "edit:.opencode/plugins/**", "deny"),
    ("tool.use", "edit:.opencode/commands/**", "deny"),
    ("tool.use", "edit:*.env", "deny"),
    ("tool.use", "edit:*.env.*", "deny"),
    ("tool.use", "edit:*.env.example", "allow"),
)


def remove_legacy_rules(updated: dict) -> None:
    """Drop old HX-owned access rules without touching unrelated user policies."""
    for field, old_rules in (("permissions", LEGACY_PERMISSIONS), ("policies", LEGACY_POLICIES)):
        current = updated.get(field)
        if current is None:
            continue
        if not isinstance(current, list):
            raise ValueError(f"Cannot migrate {field}: expected an array")
        targets = set(old_rules)
        remaining = [rule for rule in current if not (
            isinstance(rule, dict) and (rule.get("action"), rule.get("resource"), rule.get("effect")) in targets
            and set(rule.keys()) == {"action", "resource", "effect"}
        )]
        if remaining:
            updated[field] = remaining
        else:
            updated.pop(field, None)


def merge_config(existing: dict, template: dict, *, migrate_legacy: bool = False) -> dict:
    """Preserve user config; remove known legacy HX rules when upgrading HX."""
    updated = copy.deepcopy(existing)
    if migrate_legacy:
        remove_legacy_rules(updated)
    for key, value in template.items():
        if key in ("permissions", "policies"):
            current = updated.setdefault(key, [])
            if not isinstance(current, list):
                raise ValueError(f"Cannot merge {key}: expected an array")
            for rule in value:
                if rule not in current:
                    current.append(rule)
        elif key not in updated:
            updated[key] = copy.deepcopy(value)
    return updated


def ensure_regular_parents(path: Path, root: Path) -> None:
    """Refuse symlinked installation targets to avoid writing outside the destination."""
    node = path
    while node != root.parent:
        if node.is_symlink():
            raise ValueError(f"Unsafe symlink in destination: {node}")
        node = node.parent


def destination_for(mode: str, destination: str | None) -> Path:
    if destination:
        candidate = Path(destination).expanduser()
        if candidate.is_symlink():
            raise ValueError("Target directory cannot be a symlink")
        root = candidate.resolve()
    elif mode == "global":
        root = Path.home() / ".config" / "opencode"
    else:
        root = Path.cwd()
    if mode == "local":
        git = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root,
                             capture_output=True, text=True, check=False,
                             creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if git.returncode != 0 or Path(git.stdout.strip()).resolve() != root.resolve():
            raise ValueError("Local installation target must be the root of a Git repository")
    return root


def plan_install(mode: str, destination: Path, replace: bool) -> tuple[list[tuple[Path, Path]], list[Path], Path, dict]:
    source_root = SOURCE / ".opencode"
    target_root = destination if mode == "global" else destination / ".opencode"
    removals = retired_hx_files(target_root)
    if removals and not replace:
        raise ValueError("Retired HX files found; use --replace-hx for backed-up removal: "
                         + ", ".join(str(path) for path in removals))
    for path in removals:
        ensure_regular_parents(path, destination)
    actions: list[tuple[Path, Path]] = []
    for file in sorted(source_root.rglob("*")):
        if not file.is_file() or file.is_symlink() or any(part in IGNORE_PARTS for part in file.parts):
            continue
        relative = file.relative_to(source_root)
        target = target_root / relative
        ensure_regular_parents(target, destination)
        if target.is_file() and file.read_bytes() != target.read_bytes() and not replace:
            raise ValueError(f"HX file already exists and differs: {target} (use --replace-hx)")
        actions.append((file, target))
    config = destination / "opencode.jsonc"
    if mode == "local":
        for candidate in (destination / ".opencode" / "opencode.jsonc",
                          destination / ".opencode" / "opencode.json"):
            if candidate.is_file():
                config = candidate
                break
    if not config.exists() and (destination / "opencode.json").exists():
        config = destination / "opencode.json"
    ensure_regular_parents(config, destination)
    current = load_config(config) if config.exists() else {}
    template = load_config(SOURCE / "opencode.jsonc")
    # Only migrate HX rules when replacing an existing HX installation.
    previously_installed = (target_root / "hx" / "cli.py").is_file() and (
        target_root / "plugins" / "hx-command-guard" / "index.js"
    ).is_file()
    merged = merge_config(current, template, migrate_legacy=replace and previously_installed)
    # Migrate only HX's former default agent. Leave user-selected alternatives intact.
    old_default = current.get("default_agent")
    removed_hx_root = any(path.name == "root.md" for path in removals)
    if replace and (old_default in {"architect", "hx-quick-fix", "hx-root"}
                    or (old_default == "root" and removed_hx_root)):
        merged["default_agent"] = "build"
    if replace and isinstance(merged.get("agents"), dict):
        for retired in ("hx-quick-fix", "hx-root"):
            merged["agents"].pop(retired, None)
        if removed_hx_root:
            merged["agents"].pop("root", None)
    # The installer registers one shared communication policy for native and HX agents.
    # Absolute paths work globally even when a project has no local HX directory.
    communication = (target_root / "hx" / "instructions" / "communication.md").as_posix()
    if mode == "local":
        communication = ".opencode/hx/instructions/communication.md"
    instructions = merged.setdefault("instructions", [])
    if not isinstance(instructions, list):
        raise ValueError("Cannot merge instructions: expected an array")
    if communication not in instructions:
        instructions.append(communication)
    return actions, removals, config, merged


def backup_file(path: Path, root: Path, backup_root: Path) -> None:
    if not path.is_file():
        return
    target = backup_root / path.relative_to(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)


def install(mode: str, destination: Path, *, replace: bool = False, dry_run: bool = False) -> dict:
    actions, removals, config, merged = plan_install(mode, destination, replace)
    same_config = config.is_file() and load_config(config) == merged
    updates = [target for source, target in actions if not target.is_file() or target.read_bytes() != source.read_bytes()]
    if dry_run:
        return {"mode": mode, "destination": str(destination), "files_to_update": len(updates),
                "config_to_update": not same_config, "files_to_remove": len(removals), "dry_run": True}
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if mode == "local":
        common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=destination,
                                capture_output=True, text=True, check=True,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0).stdout.strip()
        git_root = (destination / common).resolve()
        backup_root = git_root / "hx" / "install-backups" / stamp
    else:
        backup_root = destination / ".hx-install-backups" / stamp
    for source, target in actions:
        if target not in updates:
            continue
        if target.is_file():
            backup_file(target, destination, backup_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    for path in removals:
        backup_file(path, destination, backup_root)
        path.unlink()
    if not same_config:
        backup_file(config, destination, backup_root)
        config.parent.mkdir(parents=True, exist_ok=True)
        temp = config.with_name(config.name + ".hx-tmp")
        temp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temp.replace(config)
    return {"mode": mode, "destination": str(destination), "files_updated": len(updates),
            "files_removed": len(removals), "config_updated": not same_config, "backup": str(backup_root) if backup_root.exists() else None,
            "hint": "Restart OpenCode, connect DeepSeek, then use /hx-plan in a Git project"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Install HX v5.8.0 globally or locally")
    parser.add_argument("mode", choices=["global", "local"])
    parser.add_argument("--target", help="Global OpenCode config directory or local Git project root")
    parser.add_argument("--replace-hx", action="store_true", help="Back up and replace conflicting managed HX files")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = install(args.mode, destination_for(args.mode, args.target),
                         replace=args.replace_hx, dry_run=args.dry_run)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error": str(error)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
