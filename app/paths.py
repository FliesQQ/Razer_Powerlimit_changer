"""Resolve project / install paths for dev and frozen exe."""

from __future__ import annotations

import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> Path:
    """Directory containing the executable (frozen) or project root (dev)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def vendor_winring0_dir() -> Path:
    """Prefer sidecar folder next to exe, then bundled vendor/."""
    base = app_dir()
    candidates = [
        base / "vendor" / "winring0",
        base,  # dll/sys placed next to BladePower.exe
        base / "_internal" / "vendor" / "winring0",
    ]
    if not is_frozen():
        candidates.insert(0, base / "vendor" / "winring0")
    for c in candidates:
        if (c / "WinRing0x64.dll").is_file() and (c / "WinRing0x64.sys").is_file():
            return c
    # Default expected location for error messages / first-run copy.
    return base if is_frozen() else (base / "vendor" / "winring0")


def profiles_path() -> Path:
    return app_dir() / "profiles.json"


def resource_path(*parts: str) -> Path:
    """Locate a bundled asset (dev root, beside exe, or PyInstaller _MEIPASS)."""
    rel = Path(*parts) if parts else Path()
    candidates: list[Path] = []
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass) / rel)
        candidates.append(app_dir() / rel)
    else:
        candidates.append(app_dir() / rel)
        candidates.append(Path(__file__).resolve().parents[1] / rel)
    for c in candidates:
        if c.is_file():
            return c
    return candidates[0] if candidates else Path(*parts)


def icon_path() -> Path:
    return resource_path("Synapse.ico")
