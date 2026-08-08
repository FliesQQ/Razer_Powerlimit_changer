"""WinRing0 loader for MSR access (admin required)."""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Optional

_STATUS = {
    0: "No error",
    1: "Unsupported platform",
    2: "Driver not loaded (run as Administrator)",
    3: "Driver not found",
    4: "Driver unloaded by other process",
    5: "Driver not loaded (network drive)",
    6: "Unknown error",
}


def _vendor_dir() -> Path:
    from app.paths import vendor_winring0_dir

    return vendor_winring0_dir()


class WinRing0:
    def __init__(self, dll_dir: Optional[Path] = None) -> None:
        self._dll = None
        self._dir = Path(dll_dir) if dll_dir else _vendor_dir()
        self._runtime_dir: Optional[Path] = None
        self._old_cwd: Optional[str] = None

    @property
    def available(self) -> bool:
        return self._dll is not None

    def _prepare_runtime(self) -> Path:
        """
        OpenLibSys looks for WinRing0x64.sys next to the process image / CWD.
        Prefer files beside the frozen exe; otherwise stage into vendor/_runtime.
        """
        src = self._dir
        needed = ["WinRing0x64.dll", "WinRing0x64.sys"]
        for name in needed:
            if not (src / name).is_file():
                raise FileNotFoundError(f"Missing {src / name}")

        exe_dir = Path(sys.executable).resolve().parent
        # Frozen: keep dll/sys next to BladePower.exe (best for driver load).
        if getattr(sys, "frozen", False) and src.resolve() == exe_dir.resolve():
            return exe_dir

        runtime = src / "_runtime"
        runtime.mkdir(exist_ok=True)
        for name in needed:
            shutil.copy2(src / name, runtime / name)

        for name in needed:
            dst = exe_dir / name
            try:
                if not dst.is_file() or dst.stat().st_size != (src / name).stat().st_size:
                    shutil.copy2(src / name, dst)
            except OSError:
                pass

        return runtime

    def initialize(self) -> None:
        if sys.maxsize <= 2**32:
            raise RuntimeError("64-bit Python is required")

        runtime = self._prepare_runtime()
        self._runtime_dir = runtime
        self._old_cwd = os.getcwd()
        os.chdir(runtime)

        dll_path = runtime / "WinRing0x64.dll"
        self._dll = ctypes.WinDLL(str(dll_path))
        self._dll.InitializeOls.restype = ctypes.c_bool
        self._dll.DeinitializeOls.restype = None
        self._dll.GetDllStatus.restype = ctypes.c_uint
        self._dll.Rdmsr.argtypes = [
            ctypes.c_uint32,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_uint32),
        ]
        self._dll.Rdmsr.restype = ctypes.c_bool
        self._dll.Wrmsr.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
        self._dll.Wrmsr.restype = ctypes.c_bool

        if not self._dll.InitializeOls():
            status = int(self._dll.GetDllStatus())
            # restore cwd before raising
            if self._old_cwd:
                os.chdir(self._old_cwd)
            raise RuntimeError(
                f"WinRing0 init failed: {_STATUS.get(status, status)} (code {status}). "
                "请用管理员运行，并将 WinRing0 加入杀软白名单。"
            )

    def close(self) -> None:
        if self._dll is not None:
            try:
                self._dll.DeinitializeOls()
            except Exception:
                pass
            self._dll = None
        if self._old_cwd:
            try:
                os.chdir(self._old_cwd)
            except Exception:
                pass
            self._old_cwd = None

    def read_msr(self, index: int) -> int:
        self._ensure()
        eax = ctypes.c_uint32()
        edx = ctypes.c_uint32()
        if not self._dll.Rdmsr(ctypes.c_uint32(index), ctypes.byref(eax), ctypes.byref(edx)):
            raise OSError(f"Rdmsr(0x{index:X}) failed")
        return (int(edx.value) << 32) | int(eax.value)

    def write_msr(self, index: int, value: int) -> None:
        self._ensure()
        eax = ctypes.c_uint32(value & 0xFFFFFFFF)
        edx = ctypes.c_uint32((value >> 32) & 0xFFFFFFFF)
        if not self._dll.Wrmsr(ctypes.c_uint32(index), eax, edx):
            raise OSError(f"Wrmsr(0x{index:X}) failed")

    def _ensure(self) -> None:
        if self._dll is None:
            raise RuntimeError("WinRing0 not initialized")
