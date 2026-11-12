"""Manifest-bound quality gate execution with explicit host/sandbox consent."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from process_utils import run
import sys
from pathlib import Path

import state
import runtime


def is_windows() -> bool:
    return sys.platform == "win32"


def detect(cwd: Path) -> list[dict]:
    """Detect independent build roots; do not silently pick only the first."""
    roots = [cwd]
    for parent in ("packages", "apps", "modules", "services"):
        directory = cwd / parent
        if directory.is_dir():
            roots.extend(path for path in sorted(directory.iterdir()) if path.is_dir() and not path.is_symlink())
    result = []
    for root in roots:
        relative = str(root.relative_to(cwd))
        commands = []
        if is_windows() and (root / "gradlew.bat").is_file():
            commands = [["cmd.exe", "/d", "/c", "gradlew.bat", task] for task in ("test", "check")]
        elif (root / "gradlew").is_file():
            commands = [["./gradlew", "test"], ["./gradlew", "check"]]
        elif is_windows() and (root / "mvnw.cmd").is_file():
            commands = [["cmd.exe", "/d", "/c", "mvnw.cmd", "verify"]]
        elif (root / "mvnw").is_file():
            commands = [["./mvnw", "verify"]]
        elif (root / "pom.xml").is_file():
            commands = [["cmd.exe", "/d", "/c", "mvn.cmd", "verify"] if is_windows() else ["mvn", "verify"]]
        elif (root / "package.json").is_file():
            package = json.loads((root / "package.json").read_text(encoding="utf-8"))
            if isinstance(package.get("scripts"), dict):
                commands = [["cmd.exe", "/d", "/c", "npm.cmd", "run", name] if is_windows() else ["npm", "run", name] for name in ("lint", "typecheck", "test", "build") if name in package["scripts"]]
        for index, argv in enumerate(commands):
            result.append({"name": f"{relative}:{index}:{argv[-1]}", "argv": argv, "cwd": relative})
    return result


def configured(cwd: Path, config: Path) -> list[dict]:
    if not config.exists():
        return detect(cwd)
    data = json.loads(config.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("gates"), list):
        raise ValueError("Quality gate config must contain a gates array")
    return data["gates"]


def validate_gate(cwd: Path, gate: dict) -> tuple[Path, list[str]]:
    if not isinstance(gate, dict) or not isinstance(gate.get("name"), str) or not gate["name"].strip():
        raise ValueError("Each Quality Gate requires a name")
    argv = gate.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and arg and "\0" not in arg for arg in argv):
        raise ValueError(f"Invalid argv in gate {gate['name']}")
    folder = gate.get("cwd", ".")
    if not isinstance(folder, str):
        raise ValueError("Gate cwd must be a relative directory")
    directory = (cwd / folder).resolve()
    if not directory.is_relative_to(cwd.resolve()) or not directory.is_dir():
        raise ValueError("Gate cwd is outside the approved worktree or does not exist")
    return directory, argv


def executable_identity(directory: Path, argv: list[str]) -> dict:
    executable = argv[0]
    found = Path(executable) if os.path.isabs(executable) else (directory / executable if "/" in executable or "\\" in executable else Path(shutil.which(executable) or ""))
    if not str(found) or not found.is_file():
        raise ValueError(f"Quality Gate executable not found: {executable}")
    resolved = found.resolve()
    if not resolved.is_file():
        raise ValueError(f"Quality Gate executable is not a file: {executable}")
    stat_info = resolved.stat()
    identity = {"path": str(resolved), "size": stat_info.st_size, "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest()}
    if is_windows() and executable.lower().endswith("cmd.exe") and len(argv) > 3 and argv[1:3] == ["/d", "/c"]:
        script = shutil.which(argv[3])
        if not script:
            candidate = directory / argv[3]
            if candidate.is_file():
                script = str(candidate)
        if not script:
            raise ValueError(f"Quality Gate command script not found: {argv[3]}")
        target = Path(script).resolve()
        identity["script"] = {"path": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    return identity


def manifest(cwd: Path, config: Path) -> dict:
    entries = []
    for gate in configured(cwd, config):
        directory, argv = validate_gate(cwd, gate)
        entries.append({"name": gate["name"], "cwd": str(directory), "argv": argv, "executable": executable_identity(directory, argv)})
    config_digest = hashlib.sha256(config.read_bytes()).hexdigest() if config.exists() else "auto-detected"
    object_data = {"schema": 1, "project": str(cwd.resolve()), "workspace_revision": state.workspace_revision(cwd), "config_sha256": config_digest, "gates": entries}
    canonical = json.dumps(object_data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {**object_data, "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def sandbox_policy(cwd: Path) -> dict:
    local = cwd / ".opencode" / "hx" / "guard" / "policy.json"
    global_path = Path.home() / ".config" / "opencode" / "hx" / "guard" / "policy.json"
    installed = runtime.HX_HOME / "guard" / "policy.json"
    base_path = global_path if global_path.is_file() else installed
    base = json.loads(base_path.read_text(encoding="utf-8")) if base_path.is_file() else {"mode": "ask-host"}
    extra = json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {}
    levels = {"ask-host": 0, "sandbox-preferred": 1, "sandbox-required": 2}
    if base.get("mode", "ask-host") not in levels or extra.get("mode", "ask-host") not in levels:
        raise ValueError("Invalid HX sandbox mode")
    result = dict(base)
    if levels[extra.get("mode", "ask-host")] > levels[base.get("mode", "ask-host")]:
        result["mode"] = extra["mode"]
    if extra.get("network") is False:
        result["network"] = False
    return result


def sandbox_argv(cwd: Path, directory: Path, argv: list[str], policy: dict) -> list[str]:
    """Use isolated workspace and HOME; never bind the host root or home."""
    executable = shutil.which("bwrap") if sys.platform.startswith("linux") else None
    if not executable:
        raise ValueError("Bubblewrap sandbox is required for this gate but unavailable")
    if not directory.is_relative_to(cwd.resolve()):
        raise ValueError("Gate cwd outside sandbox workspace")
    args = [executable, "--die-with-parent", "--new-session", "--unshare-all"]
    if policy.get("network") is True:
        args.append("--share-net")
    for directory_name in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(directory_name).exists():
            args += ["--ro-bind", directory_name, directory_name]
    args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp", "--dir", "/tmp/hx-home",
             "--dir", "/workspace", "--bind", str(cwd.resolve()), "/workspace",
             "--clearenv", "--setenv", "HOME", "/tmp/hx-home", "--setenv", "PATH", "/usr/local/bin:/usr/bin:/bin",
             "--chdir", "/workspace/" + str(directory.relative_to(cwd.resolve())), "--"]
    return args + argv


def run_gate(cwd: Path, gate: dict, timeout: int, *, policy: dict | None = None) -> dict:
    result = {"name": gate["name"], "argv": gate["argv"], "cwd": gate["cwd"]}
    try:
        policy = policy or sandbox_policy(cwd)
        mode = policy.get("mode", "ask-host")
        directory = Path(gate["cwd"])
        argv = gate["argv"]
        if mode in ("sandbox-required", "sandbox-preferred"):
            argv = sandbox_argv(cwd, directory, argv, policy)
        elif mode != "ask-host":
            raise ValueError(f"Unknown sandbox mode: {mode}")
        proc = run(argv, cwd=directory, capture_output=True, text=True, timeout=timeout, check=False)
        output = (proc.stdout + "\n" + proc.stderr)[-12000:]
        result.update(status="PASS" if proc.returncode == 0 else "FAIL", exit_code=proc.returncode, output=output, mode=mode)
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
        result.update(status="FAIL", error=str(exc))
    return result


def execute(cwd: Path, config: Path, *, expected_sha: str | None = None, host_approved: bool = False, timeout: int = 600) -> dict:
    manifest_data = manifest(cwd, config)
    if not manifest_data["gates"]:
        return {"status": "UNVERIFIED", "reason": "No applicable Quality Gates; configure explicit gates for SQL or monorepos", "results": [], "manifest_sha256": manifest_data["sha256"]}
    if not expected_sha or manifest_data["sha256"] != expected_sha:
        raise ValueError("Quality Gates manifest was not approved or changed since preview")
    policy = sandbox_policy(cwd)
    if policy.get("mode", "ask-host") == "ask-host" and not host_approved:
        raise ValueError("Host execution needs an explicit permission prompt for this manifest")
    results = []
    for gate in manifest_data["gates"]:
        # Re-hash the whole manifest before every child process to defeat configuration/executable changes.
        if manifest(cwd, config)["sha256"] != expected_sha:
            results.append({"name": gate["name"], "status": "FAIL", "error": "Manifest changed during checks"})
            break
        results.append(run_gate(cwd, gate, timeout, policy=policy))
        if results[-1]["status"] != "PASS":
            break
        if manifest(cwd, config)["sha256"] != expected_sha:
            results[-1]["status"] = "FAIL"
            results[-1]["error"] = "Workspace or gate configuration changed during execution; reapprove and rerun"
            break
    return {"status": "PASS" if len(results) == len(manifest_data["gates"]) and all(item["status"] == "PASS" for item in results) else "FAIL",
            "manifest_sha256": expected_sha, "results": results,
            "execution_notice": "Approval covers the listed parent processes, not each child process they spawn"}
