"""Run HX child processes without flashing console windows on Windows."""

from __future__ import annotations

import os
import subprocess


def run(*args, **kwargs):
    """Preserve subprocess.run behavior while disabling new Windows consoles."""
    kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    return subprocess.run(*args, **kwargs)
