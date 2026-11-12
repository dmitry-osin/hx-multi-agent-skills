"""Independent read-only reviews; no HX plan or worktree approval required."""

from __future__ import annotations

import hashlib
import hmac
import json
import subprocess
from process_utils import run
from pathlib import Path

import runtime
import state
import review_contract


def git(cwd: Path, *args: str, text: bool = True):
    """Run a fixed git subcommand without passing through a command shell."""
    return run(["git", "--no-pager", *args], cwd=cwd,
                          capture_output=True, text=text, check=True).stdout


def resolve_commit(cwd: Path, value: str) -> str:
    """Accept hexadecimal commit IDs only, never flags or Git revision expressions."""
    if not isinstance(value, str) or not 7 <= len(value) <= 40 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise ValueError("Commit target must be a 7-40 digit hexadecimal Git SHA")
    sha = git(cwd, "rev-parse", "--verify", f"{value}^{{commit}}").strip()
    if len(sha) != 40:
        raise ValueError("Unable to resolve commit SHA")
    return sha


def target_revision(cwd: Path, target: str | None, base: str | None = None) -> tuple[str, str]:
    if base:
        if not target:
            raise ValueError("A commit range requires both base and target")
        resolved = resolve_commit(cwd, target)
        start = resolve_commit(cwd, base)
        return "range", hashlib.sha256(f"{start}..{resolved}".encode()).hexdigest()
    if target:
        return "commit", resolve_commit(cwd, target)
    return "workspace", state.workspace_revision(cwd)


def validate_payload(cwd: Path, signed: dict, kind: str, target: str | None, base: str | None) -> tuple[dict, dict]:
    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        raise ValueError("HX standalone reviews require jsonschema==4.26.0; install from hx/requirements.txt") from exc

    if not isinstance(signed, dict) or not isinstance(signed.get("payload"), str):
        raise ValueError("A signed hx_submit_review payload is required")
    secret_file = state.state_dir(cwd) / "attest.key"
    if not secret_file.is_file():
        raise ValueError("Missing plugin review attestation key")
    expected = hmac.new(secret_file.read_bytes(), signed["payload"].encode(), hashlib.sha256).hexdigest()
    if not isinstance(signed.get("signature"), str) or not hmac.compare_digest(expected, signed["signature"]):
        raise ValueError("Invalid review provenance signature")
    payload = json.loads(signed["payload"])
    agent = "reviewer" if kind == "review" else "security-auditor"
    if payload.get("agent") != agent or not payload.get("session_id") or not payload.get("message_id"):
        raise ValueError("Review must originate from the selected dedicated agent session")
    target_kind, sha = target_revision(cwd, target, base)
    if payload.get("target_kind") != target_kind or payload.get("target_sha256") != sha:
        raise ValueError("Review target changed since the report was created")
    report = payload.get("report")
    report = review_contract.validate(cwd, report, commit=resolve_commit(cwd, target) if target else None)
    return payload, report


def record(cwd: Path, report_file: Path, kind: str, target: str | None, base: str | None = None) -> dict:
    if kind not in ("review", "security"):
        raise ValueError("Unknown standalone review kind")
    signed = json.loads(report_file.read_text(encoding="utf-8"))
    payload, report = validate_payload(cwd, signed, kind, target, base)
    _, sha = target_revision(cwd, target, base)
    destination = state.state_dir(cwd) / "standalone-reviews" / sha / (kind + ".json")
    state.write_json(destination, {
        "target": {"type": payload["target_kind"], "sha256": sha},
        "agent": payload["agent"], "session_id": payload["session_id"],
        "message_id": payload["message_id"], "report": report,
        "attestation": "Signed by the local HX plugin; not independent proof of report correctness",
    })
    return {"mode": "STANDALONE", "target": sha, "kind": kind,
            "verdict": report["verdict"], "coverage": report["coverage"], "saved_to": str(destination)}
