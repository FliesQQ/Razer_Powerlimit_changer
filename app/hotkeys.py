"""Global hotkey registration."""

from __future__ import annotations

from typing import Callable, Dict, Optional


class HotkeyService:
    def __init__(self) -> None:
        self._registered: list[str] = []
        self._backend = None
        try:
            import keyboard

            self._backend = keyboard
        except Exception:
            self._backend = None

    @property
    def available(self) -> bool:
        return self._backend is not None

    def clear(self) -> None:
        if not self._backend:
            return
        for hk in self._registered:
            try:
                self._backend.remove_hotkey(hk)
            except Exception:
                pass
        self._registered.clear()

    def register_map(self, mapping: Dict[str, Callable[[], None]]) -> list[str]:
        """mapping: hotkey -> callback. Returns list of failed hotkeys."""
        failed: list[str] = []
        self.clear()
        if not self._backend:
            return list(mapping.keys())
        for hk, cb in mapping.items():
            try:
                self._backend.add_hotkey(hk, cb, suppress=False)
                self._registered.append(hk)
            except Exception:
                failed.append(hk)
        # Always try restore default on ctrl+alt+0 if provided separately by caller.
        return failed
