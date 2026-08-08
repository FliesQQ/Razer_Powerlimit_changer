"""Admin elevation helpers."""

from __future__ import annotations

import ctypes
import sys


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relaunch current script/exe with UAC elevation. Returns True if elevation requested."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv)
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        exe,
        params if params else None,
        None,
        1,
    )
    return rc > 32
