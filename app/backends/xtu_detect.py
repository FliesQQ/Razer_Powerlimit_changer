"""Detect and persist Intel Extreme Tuning Utility (XTU / IET) install path."""

from __future__ import annotations

import winreg
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


KNOWN_PATHS = [
    Path(r"C:\Program Files\Intel\Intel(R) Extreme Tuning Utility"),
    Path(r"C:\Program Files (x86)\Intel\Intel(R) Extreme Tuning Utility"),
]


def _looks_like_xtu(path: Path) -> bool:
    if not path.is_dir():
        return False
    markers = [
        path / "Client",
        path / "Binaries",
        path / "Client" / "ProfilesApi.dll",
        path / "Binaries" / "XtuService.exe",
        path / "XtuCli.exe",
    ]
    return any(m.exists() for m in markers)


def _from_uninstall_registry() -> Optional[Path]:
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
        ),
    ]
    for hive, sub in roots:
        try:
            with winreg.OpenKey(hive, sub) as root:
                for i in range(0, winreg.QueryInfoKey(root)[0]):
                    try:
                        name = winreg.EnumKey(root, i)
                        with winreg.OpenKey(root, name) as key:
                            display, _ = winreg.QueryValueEx(key, "DisplayName")
                            if "Extreme Tuning" not in str(display) and "XTU" not in str(display):
                                continue
                            try:
                                loc, _ = winreg.QueryValueEx(key, "InstallLocation")
                            except OSError:
                                loc = ""
                            if loc and _looks_like_xtu(Path(loc)):
                                return Path(loc)
                            # InstallLocation often empty for XTU — fall back to known paths.
                    except OSError:
                        continue
        except OSError:
            continue
    return None


def detect_xtu_path() -> Optional[Path]:
    for p in KNOWN_PATHS:
        if _looks_like_xtu(p):
            return p.resolve()
    found = _from_uninstall_registry()
    if found:
        return found.resolve()
    return None


def detect_and_record(existing: Optional[str] = None) -> dict:
    """
    Detect XTU/IET and return a settings dict suitable for persistence.

    If a previously saved path still looks valid, keep it; otherwise refresh.
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if existing:
        p = Path(existing)
        if _looks_like_xtu(p):
            return {
                "xtu_path": str(p.resolve()),
                "xtu_found": True,
                "xtu_detected_at": now,
                "xtu_source": "cached",
            }

    found = detect_xtu_path()
    if found:
        return {
            "xtu_path": str(found),
            "xtu_found": True,
            "xtu_detected_at": now,
            "xtu_source": "scan",
        }
    return {
        "xtu_path": existing or "",
        "xtu_found": False,
        "xtu_detected_at": now,
        "xtu_source": "scan",
    }
