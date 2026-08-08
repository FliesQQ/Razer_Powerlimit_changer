"""Silent MSI Afterburner profile switching."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional


CANDIDATE_PATHS = [
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "MSI Afterburner"
    / "MSIAfterburner.exe",
    Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
    / "MSI Afterburner"
    / "MSIAfterburner.exe",
]


class AfterburnerBackend:
    def __init__(self, exe_path: Optional[str] = None) -> None:
        self.exe = Path(exe_path) if exe_path else self._discover()

    @staticmethod
    def _discover() -> Optional[Path]:
        for p in CANDIDATE_PATHS:
            if p.is_file():
                return p
        return None

    @property
    def available(self) -> bool:
        return self.exe is not None and self.exe.is_file()

    def apply_profile(self, profile_index: int) -> str:
        if not self.available:
            raise RuntimeError("MSI Afterburner not found")
        if profile_index < 1 or profile_index > 5:
            raise ValueError("Afterburner profile must be 1..5")
        assert self.exe is not None
        # Start/apply without focusing UI when possible.
        creationflags = 0
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            creationflags |= subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        subprocess.Popen(
            [str(self.exe), f"-Profile{profile_index}"],
            cwd=str(self.exe.parent),
            creationflags=creationflags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Profile{profile_index}"
