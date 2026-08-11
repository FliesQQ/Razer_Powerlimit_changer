"""System tray helper (optional)."""

from __future__ import annotations

import threading
from typing import Callable, Optional


def _load_tray_image():
    from PIL import Image, ImageDraw

    try:
        from app.paths import icon_path

        path = icon_path()
        if path.is_file():
            img = Image.open(path)
            # pystray works best with RGBA; keep a reasonable tray size.
            img = img.convert("RGBA")
            if max(img.size) > 64:
                img = img.resize((64, 64), Image.Resampling.LANCZOS)
            return img
    except Exception:
        pass

    image = Image.new("RGBA", (64, 64), color=(20, 90, 60, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 52, 52), fill=(80, 220, 140, 255))
    return image


def _wrap(fn: Callable[[], None]) -> Callable:
    """pystray calls handlers as callback(icon, item) — ignore those args."""

    def handler(icon=None, item=None):
        fn()

    return handler


class TrayService:
    def __init__(
        self,
        *,
        on_show: Callable[[], None],
        on_quit: Callable[[], None],
        # (profile_id, display_name) in tray menu order.
        get_tray_profiles: Callable[[], list[tuple[str, str]]],
        on_select_profile: Callable[[str], None],
        get_active_profile_id: Callable[[], Optional[str]],
        get_sensor_tray_visible: Optional[Callable[[], bool]] = None,
        on_toggle_sensor_tray: Optional[Callable[[], None]] = None,
        get_osd_visible: Optional[Callable[[], bool]] = None,
        on_toggle_osd: Optional[Callable[[], None]] = None,
        get_autostart: Optional[Callable[[], bool]] = None,
        on_toggle_autostart: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_show = on_show
        self.on_quit = on_quit
        self.get_tray_profiles = get_tray_profiles
        self.on_select_profile = on_select_profile
        self.get_active_profile_id = get_active_profile_id
        self.get_sensor_tray_visible = get_sensor_tray_visible
        self.on_toggle_sensor_tray = on_toggle_sensor_tray
        self.get_osd_visible = get_osd_visible
        self.on_toggle_osd = on_toggle_osd
        self.get_autostart = get_autostart
        self.on_toggle_autostart = on_toggle_autostart
        self._icon = None
        self._thread: Optional[threading.Thread] = None
        self._tooltip = "BladePower"
        self._pystray = None

    def set_tooltip(self, text: str) -> None:
        """Update mouse-hover tooltip (Windows: icon title)."""
        tip = (text or "").strip() or "BladePower"
        self._tooltip = tip
        icon = self._icon
        if icon is None:
            return
        try:
            icon.title = tip
        except Exception:
            pass

    def _build_menu(self):
        assert self._pystray is not None
        pystray = self._pystray
        menu_items = [
            pystray.MenuItem("显示窗口", _wrap(self.on_show), default=True)
        ]

        profiles = []
        try:
            profiles = list(self.get_tray_profiles() or [])
        except Exception:
            profiles = []

        if profiles:
            menu_items.append(pystray.Menu.SEPARATOR)

        for pid, name in profiles:
            # Bind pid in defaults so the loop does not capture the last id.
            def _checked(_item=None, profile_id=pid):
                try:
                    return self.get_active_profile_id() == profile_id
                except Exception:
                    return False

            menu_items.append(
                pystray.MenuItem(
                    name,
                    _wrap(lambda profile_id=pid: self.on_select_profile(profile_id)),
                    checked=_checked,
                    radio=True,
                )
            )

        if self.on_toggle_sensor_tray is not None:
            def _checked_sensors(_item=None):
                if self.get_sensor_tray_visible:
                    try:
                        return bool(self.get_sensor_tray_visible())
                    except Exception:
                        return False
                return False

            menu_items.append(pystray.Menu.SEPARATOR)
            menu_items.append(
                pystray.MenuItem(
                    "托盘传感器（功耗/温度）",
                    _wrap(self.on_toggle_sensor_tray),
                    checked=_checked_sensors,
                )
            )

        if self.on_toggle_osd is not None:
            def _checked_osd(_item=None):
                if self.get_osd_visible:
                    try:
                        return bool(self.get_osd_visible())
                    except Exception:
                        return False
                return False

            if self.on_toggle_sensor_tray is None:
                menu_items.append(pystray.Menu.SEPARATOR)
            menu_items.append(
                pystray.MenuItem(
                    "桌面性能 OSD",
                    _wrap(self.on_toggle_osd),
                    checked=_checked_osd,
                )
            )

        if self.on_toggle_autostart is not None:
            def _checked_autostart(_item=None):
                if self.get_autostart:
                    try:
                        return bool(self.get_autostart())
                    except Exception:
                        return False
                return False

            if self.on_toggle_sensor_tray is None and self.on_toggle_osd is None:
                menu_items.append(pystray.Menu.SEPARATOR)
            menu_items.append(
                pystray.MenuItem(
                    "开机自动启动",
                    _wrap(self.on_toggle_autostart),
                    checked=_checked_autostart,
                )
            )

        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem("退出", _wrap(self.on_quit)))
        return pystray.Menu(*menu_items)

    def refresh_menu(self) -> None:
        """Rebuild menu after tray-visible profile list changes."""
        icon = self._icon
        if icon is None or self._pystray is None:
            return
        try:
            icon.menu = self._build_menu()
            update = getattr(icon, "update_menu", None)
            if callable(update):
                update()
        except Exception:
            pass

    def start(self) -> bool:
        try:
            import pystray
        except Exception:
            return False

        self._pystray = pystray
        image = _load_tray_image()
        self._icon = pystray.Icon(
            "BladePower",
            image,
            self._tooltip,
            menu=self._build_menu(),
        )
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
