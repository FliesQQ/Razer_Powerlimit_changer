"""Physical memory (MMIO) access with multiple Windows backends.

WinRing0 ReadPhysicalMemory often fails under modern Win11 / VBS, or is a
non-functional stub. Fallbacks:
  1) WinRing0 (several calling conventions)
  2) inpoutx64.dll GetPhysLong / SetPhysLong
  3) MSI Afterburner RTCore64 device IOCTL
"""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from pathlib import Path
from typing import Optional


class PhysMemError(OSError):
    pass


class PhysMem:
    def read_dword(self, address: int) -> int:
        raise NotImplementedError

    def write_dword(self, address: int, value: int) -> None:
        raise NotImplementedError

    def read_qword(self, address: int) -> int:
        lo = self.read_dword(address)
        hi = self.read_dword(address + 4)
        return (hi << 32) | lo

    def write_qword(self, address: int, value: int) -> None:
        self.write_dword(address, value & 0xFFFFFFFF)
        self.write_dword(address + 4, (value >> 32) & 0xFFFFFFFF)


class WinRing0PhysMem(PhysMem):
    def __init__(self, ring0) -> None:
        self._r0 = ring0
        self._dll = ring0._dll
        # Prefer DWORD return (bytes transferred); also accept BOOL.
        try:
            self._dll.ReadPhysicalMemory.restype = ctypes.c_uint32
            self._dll.WritePhysicalMemory.restype = ctypes.c_uint32
        except Exception:
            pass

    def read_dword(self, address: int) -> int:
        errors: list[str] = []
        for count, unit in ((4, 1), (1, 4)):
            buf = (ctypes.c_ubyte * 4)()
            try:
                rc = self._dll.ReadPhysicalMemory(
                    ctypes.c_size_t(address),
                    buf,
                    ctypes.c_uint32(count),
                    ctypes.c_uint32(unit),
                )
                if int(rc) != 0:
                    return int.from_bytes(bytes(buf), "little")
                errors.append(f"conv({count},{unit})=0")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"conv({count},{unit}):{exc}")
        raise PhysMemError(
            f"WinRing0 ReadPhysicalMemory(0x{address:X}) failed ({'; '.join(errors)})"
        )

    def write_dword(self, address: int, value: int) -> None:
        errors: list[str] = []
        raw = int(value & 0xFFFFFFFF).to_bytes(4, "little")
        for count, unit in ((4, 1), (1, 4)):
            buf = (ctypes.c_ubyte * 4).from_buffer_copy(raw)
            try:
                rc = self._dll.WritePhysicalMemory(
                    ctypes.c_size_t(address),
                    buf,
                    ctypes.c_uint32(count),
                    ctypes.c_uint32(unit),
                )
                if int(rc) != 0:
                    return
                errors.append(f"conv({count},{unit})=0")
            except Exception as exc:  # noqa: BLE001
                errors.append(f"conv({count},{unit}):{exc}")
        raise PhysMemError(
            f"WinRing0 WritePhysicalMemory(0x{address:X}) failed ({'; '.join(errors)})"
        )


class InpOutPhysMem(PhysMem):
    def __init__(self, dll_path: Path) -> None:
        self._dll = ctypes.WinDLL(str(dll_path))
        # BOOL GetPhysLong(PBYTE pbPhysAddr, PDWORD pdwPhysVal);
        self._dll.GetPhysLong.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        self._dll.GetPhysLong.restype = ctypes.c_bool
        self._dll.SetPhysLong.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self._dll.SetPhysLong.restype = ctypes.c_bool
        # Optional open check
        if hasattr(self._dll, "IsInpOutDriverOpen"):
            self._dll.IsInpOutDriverOpen.restype = ctypes.c_bool
            if not self._dll.IsInpOutDriverOpen():
                raise PhysMemError(f"InpOut 驱动未打开: {dll_path}")

    def read_dword(self, address: int) -> int:
        val = ctypes.c_uint32()
        if not self._dll.GetPhysLong(ctypes.c_void_p(address), ctypes.byref(val)):
            raise PhysMemError(f"InpOut GetPhysLong(0x{address:X}) failed")
        return int(val.value)

    def write_dword(self, address: int, value: int) -> None:
        if not self._dll.SetPhysLong(ctypes.c_void_p(address), ctypes.c_uint32(value & 0xFFFFFFFF)):
            raise PhysMemError(f"InpOut SetPhysLong(0x{address:X}) failed")


class RTCorePhysMem(PhysMem):
    """MSI Afterburner RTCore64.sys physical memory IOCTL backend."""

    IOCTL_READ = 0x80002048
    IOCTL_WRITE = 0x8000204C

    def __init__(self) -> None:
        kernel32 = ctypes.windll.kernel32
        GENERIC_READ = 0x80000000
        GENERIC_WRITE = 0x40000000
        OPEN_EXISTING = 3
        kernel32.CreateFileW.restype = wintypes.HANDLE
        handle = kernel32.CreateFileW(
            "\\\\.\\RTCore64",
            GENERIC_READ | GENERIC_WRITE,
            0,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        # INVALID_HANDLE_VALUE is (HANDLE)-1 on both 32/64-bit.
        if handle is None or int(handle) in (-1, 0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF):
            raise PhysMemError("无法打开 \\\\.\\RTCore64（需安装 MSI Afterburner）")
        self._handle = handle
        self._k32 = kernel32

    def close(self) -> None:
        try:
            self._k32.CloseHandle(self._handle)
        except Exception:
            pass

    def _ioctl(self, code: int, address: int, size: int, value: int = 0) -> int:
        # RTC64_MEMORY_STRUCT (48 bytes) — confirmed by CVE-2019-16098 research:
        #   0x00 pad[8]
        #   0x08 Address (u64)
        #   0x10 pad[4]
        #   0x14 Offset (u32, usually 0)
        #   0x18 Size (u32: 1/2/4)
        #   0x1C Value (u32)
        #   0x20 pad[16]
        buf = bytearray(48)
        struct.pack_into("<Q", buf, 0x08, address & 0xFFFFFFFFFFFFFFFF)
        struct.pack_into("<I", buf, 0x14, 0)  # Offset
        struct.pack_into("<I", buf, 0x18, int(size))
        struct.pack_into("<I", buf, 0x1C, value & 0xFFFFFFFF)
        out = ctypes.create_string_buffer(bytes(buf), len(buf))
        returned = wintypes.DWORD(0)
        ok = self._k32.DeviceIoControl(
            self._handle,
            code,
            out,
            len(buf),
            out,
            len(buf),
            ctypes.byref(returned),
            None,
        )
        if not ok:
            err = ctypes.GetLastError()
            raise PhysMemError(f"RTCore64 IOCTL 0x{code:X} failed (err={err})")
        return struct.unpack_from("<I", out.raw, 0x1C)[0]

    def read_dword(self, address: int) -> int:
        return self._ioctl(self.IOCTL_READ, address, 4)

    def write_dword(self, address: int, value: int) -> None:
        self._ioctl(self.IOCTL_WRITE, address, 4, value)


def _inpout_candidates() -> list[Path]:
    from app.paths import app_dir

    bases = [
        app_dir(),
        app_dir() / "vendor",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "MSI Afterburner",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "MSI Afterburner",
        Path(r"C:\Windows\System32"),
        Path(r"C:\Windows\SysWOW64"),
    ]
    names = ("inpoutx64.dll", "InpOutx64.dll", "inpout32.dll")
    out: list[Path] = []
    for b in bases:
        for n in names:
            p = b / n
            if p.is_file():
                out.append(p)
    return out


_cached: Optional[PhysMem] = None
_cached_name: str = ""
_last_error: str = ""


def get_physmem(ring0=None, *, probe_address: Optional[int] = None) -> PhysMem:
    """Return a working PhysMem backend (cached). Raises PhysMemError if none work."""
    global _cached, _cached_name, _last_error
    if _cached is not None:
        return _cached

    errors: list[str] = []
    candidates: list[tuple[str, PhysMem]] = []

    # Prefer RTCore64 / InpOut: WinRing0 ReadPhysicalMemory often returns 0 on Win11.
    try:
        candidates.append(("RTCore64", RTCorePhysMem()))
    except Exception as exc:  # noqa: BLE001
        errors.append(f"RTCore64-init:{exc}")

    for path in _inpout_candidates():
        try:
            candidates.append((f"InpOut({path.name})", InpOutPhysMem(path)))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"InpOut-init:{exc}")

    if ring0 is not None:
        try:
            candidates.append(("WinRing0", WinRing0PhysMem(ring0)))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"WinRing0-init:{exc}")

    for name, backend in candidates:
        try:
            if probe_address is not None:
                backend.read_dword(probe_address)
            _cached = backend
            _cached_name = name
            return _cached
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{name}:{exc}")
            if isinstance(backend, RTCorePhysMem):
                try:
                    backend.close()
                except Exception:
                    pass

    _last_error = " | ".join(errors) if errors else "无可用物理内存后端"
    raise PhysMemError(
        "无法访问物理内存(MMIO)。"
        "请到 Windows 安全中心关闭「核心隔离 → 内存完整性」并重启；"
        "或安装 MSI Afterburner（提供 RTCore64）；"
        "也可将 inpoutx64.dll 放到程序目录。"
        f" 详情: {_last_error}"
    )


def backend_name() -> str:
    return _cached_name or ""


def reset_cache() -> None:
    global _cached, _cached_name
    if isinstance(_cached, RTCorePhysMem):
        try:
            _cached.close()
        except Exception:
            pass
    _cached = None
    _cached_name = ""
