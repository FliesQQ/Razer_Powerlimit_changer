"""Apply application icon to a Tk root / Toplevel (Windows-reliable)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Optional

_photo_keep: list = []
_temp_ico: Optional[Path] = None


def _ensure_multi_size_ico(src: Path) -> Path:
    """
    Tk / Win32 title-bar icons need 16/32/48 sizes.
    Prefer the source file when it already contains multiple sizes.
    """
    global _temp_ico
    try:
        from PIL import IcoImagePlugin

        with open(src, "rb") as f:
            entries = list(IcoImagePlugin.IcoFile(f).sizes())
        if len(entries) >= 3 and (16, 16) in entries and (32, 32) in entries:
            return src
    except Exception:
        pass

    try:
        from PIL import Image
    except Exception:
        return src

    try:
        im = Image.open(src).convert("RGBA")
        sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
        out = Path(tempfile.gettempdir()) / "BladePower_window.ico"
        # Pillow expands one RGBA image into the requested ICO mip levels.
        im.save(out, format="ICO", sizes=sizes)
        _temp_ico = out
        return out
    except Exception:
        return src


def apply_window_icon(root) -> bool:
    """
    Set window / taskbar icon. Returns True if at least one method succeeded.
    Keeps PhotoImage references alive for the process lifetime.
    """
    from .paths import icon_path

    src = icon_path()
    if not src.is_file():
        return False

    try:
        root.update_idletasks()
    except Exception:
        pass

    ico = _ensure_multi_size_ico(src)
    ok = False

    # 1) Classic Tk .ico path (title bar on Windows).
    try:
        path = str(ico.resolve())
        root.iconbitmap(path)
        try:
            root.iconbitmap(default=path)
        except Exception:
            pass
        ok = True
    except Exception:
        pass

    # 2) iconphoto (helps some Tk builds / Alt-Tab).
    try:
        from PIL import Image, ImageTk

        im = Image.open(src).convert("RGBA")
        # Prefer a mid size for PhotoImage.
        if max(im.size) > 64:
            im = im.resize((64, 64), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(im)
        _photo_keep.append(photo)
        root.iconphoto(True, photo)
        ok = True
    except Exception:
        pass

    # 3) Win32 WM_SETICON — most reliable for taskbar + title bar under frozen exe.
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            WM_SETICON = 0x0080
            ICON_SMALL = 0
            ICON_BIG = 1
            IMAGE_ICON = 1
            LR_LOADFROMFILE = 0x0010
            LR_DEFAULTSIZE = 0x0040

            hwnd = int(root.winfo_id())
            path = str(ico.resolve())

            LoadImageW = user32.LoadImageW
            LoadImageW.argtypes = [
                wintypes.HINSTANCE,
                wintypes.LPCWSTR,
                wintypes.UINT,
                ctypes.c_int,
                ctypes.c_int,
                wintypes.UINT,
            ]
            LoadImageW.restype = wintypes.HANDLE

            h_small = LoadImageW(None, path, IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
            h_big = LoadImageW(None, path, IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
            if not h_big:
                h_big = LoadImageW(None, path, IMAGE_ICON, 0, 0, LR_LOADFROMFILE | LR_DEFAULTSIZE)

            if h_small:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, h_small)
                ok = True
            if h_big:
                user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, h_big)
                ok = True

            # Also set on owner / toplevel if different.
            try:
                root.update_idletasks()
                # Tk frame HWND sometimes differs; set on both.
                GWL_HWNDPARENT = -8
                get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
                parent = get_long(hwnd, GWL_HWNDPARENT)
                if parent and int(parent) not in (0, hwnd):
                    if h_small:
                        user32.SendMessageW(int(parent), WM_SETICON, ICON_SMALL, h_small)
                    if h_big:
                        user32.SendMessageW(int(parent), WM_SETICON, ICON_BIG, h_big)
            except Exception:
                pass

            # Keep handles referenced so GC doesn't free them oddly via ctypes.
            _photo_keep.extend([h_small, h_big, path])
            _ = kernel32  # silence lint
        except Exception:
            pass

    return ok
