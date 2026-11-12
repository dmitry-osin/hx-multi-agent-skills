"""Resolve HX installation files independently from the current Git checkout."""

from __future__ import annotations

from pathlib import Path


HX_HOME = Path(__file__).resolve().parent


def project_override(cwd: Path, name: str) -> Path:
    """Prefer a project-specific HX setting, then the active installation setting."""
    project = cwd.resolve() / ".opencode" / "hx" / name
    return project if project.is_file() else HX_HOME / name


def local_install_for(cwd: Path) -> bool:
    """True only when this exact HX runtime lives in the checkout."""
    return HX_HOME == (cwd.resolve() / ".opencode" / "hx").resolve()
