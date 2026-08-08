"""Helpers to avoid Razer Synapse UI relaunch when talking to Blade HID."""

from __future__ import annotations

import time
from typing import Iterable, Set

SYNAPSE_UI_NAMES = {
    "razersynapse",
    "razersynapse3",
    "razersynapse4",
    "razer synapse 3",
    "razer synapse 4",
    "razer central",
    "razerappengine",
    "synapse3",
    "synapse4",
}


def list_synapse_ui_pids() -> Set[int]:
    try:
        import psutil
    except ImportError:
        return _list_via_tasklist()

    pids: Set[int] = set()
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = (proc.info.get("name") or "").lower().replace(".exe", "")
            if any(key in name for key in SYNAPSE_UI_NAMES):
                pids.add(int(proc.info["pid"]))
        except Exception:
            continue
    return pids


def _list_via_tasklist() -> Set[int]:
    import subprocess

    pids: Set[int] = set()
    try:
        out = subprocess.check_output(
            ["tasklist", "/FO", "CSV", "/NH"],
            text=True,
            encoding="utf-8",
            errors="ignore",
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
    except Exception:
        return pids
    for line in out.splitlines():
        low = line.lower()
        if not any(k in low for k in ("razer", "synapse")):
            continue
        # "name","pid","session","session#","mem"
        parts = [p.strip().strip('"') for p in line.split(",")]
        if len(parts) < 2:
            continue
        name = parts[0].lower().replace(".exe", "")
        if any(key in name for key in SYNAPSE_UI_NAMES):
            try:
                pids.add(int(parts[1]))
            except ValueError:
                pass
    return pids


def kill_pids(pids: Iterable[int]) -> int:
    killed = 0
    try:
        import psutil

        for pid in pids:
            try:
                psutil.Process(pid).terminate()
                killed += 1
            except Exception:
                pass
        return killed
    except ImportError:
        import subprocess

        for pid in pids:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW
                    if hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0,
                )
                killed += 1
            except Exception:
                pass
        return killed


def snapshot_and_suppress(before: Set[int], wait_s: float = 0.8) -> int:
    """Kill Synapse UI processes that appeared after HID access."""
    time.sleep(wait_s)
    after = list_synapse_ui_pids()
    newborn = after - before
    if not newborn:
        return 0
    return kill_pids(newborn)
