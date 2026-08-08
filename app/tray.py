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
        profile_actions: list[tuple[str, Callable[[], None]]],
        get_sensor_tray_visible: Optional[Callable[[], bool]] = None,
        on_toggle_sensor_tray: Optional[Callable[[], None]] = None,
        get_osd_visible: Optional[Callable[[], bool]] = None,
        on_toggle_osd: Optional[Callable[[], None]] = None,
        get_autostart: Optional[Callable[[], bool]] = None,
        on_toggle_autostart: Optional[Callable[[], None]] = None,
    ) -> None:
        self.on_show = on_show
        self.on_quit = on_quit
        self.profile_actions = profile_actions
        self.get_sensor_tray_visible = get_sensor_tray_visible
        self.on_toggle_sensor_tray = on_toggle_sensor_tray
        self.get_osd_visible = get_osd_visible
        self.on_toggle_osd = on_toggle_osd
        self.get_autostart = get_autostart
        self.on_toggle_autostart = on_toggle_autostart
        self._icon = None
        self._thread: Optional[threading.Thread] = None

    def start(self) -> bool:
        try:
            import pystray
        except Exception:
            return False

        image = _load_tray_image()

        # default=True → Windows 下双击托盘图标触发「显示窗口」
        menu_items = [
            pystray.MenuItem("显示窗口", _wrap(self.on_show), default=True)
        ]
        for name, action in self.profile_actions:
            # Bind action in default-arg so the loop does not capture the last one.
            menu_items.append(pystray.MenuItem(name, _wrap(action)))

        if self.on_toggle_sensor_tray is not None:
            def _checked_sensors(_item=None):
                if self.get_sensor_tray_visible:
                    try:
                        return bool(self.get_sensor_tray_visible())
                    except Exception:
                        return False
                return False

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

            menu_items.append(
                pystray.MenuItem(
                    "开机自动启动",
                    _wrap(self.on_toggle_autostart),
                    checked=_checked_autostart,
                )
            )

        menu_items.append(pystray.MenuItem("退出", _wrap(self.on_quit)))

        self._icon = pystray.Icon(
            "BladePower",
            image,
            "Blade Power Switcher",
            menu=pystray.Menu(*menu_items),
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
