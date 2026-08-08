"""HWiNFO-style multi sensor tray icons (CPU/GPU power & temp)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

DEFAULT_ORDER = ["cpu_pwr", "cpu_tmp", "gpu_pwr", "gpu_tmp"]

SENSOR_SPECS: dict[str, tuple[str, tuple[int, int, int]]] = {
    "cpu_pwr": ("CPU Package Power", (180, 90, 20)),
    "cpu_tmp": ("CPU Package Temp", (160, 40, 40)),
    "gpu_pwr": ("GPU Power", (30, 110, 50)),
    "gpu_tmp": ("GPU Temp", (30, 80, 150)),
}


@dataclass
class SensorSnapshot:
    cpu_power_w: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    gpu_power_w: Optional[float] = None
    gpu_temp_c: Optional[float] = None


def _load_font(size: int):
    from PIL import ImageFont

    for path in (
        r"C:\Windows\Fonts\consolab.ttf",
        r"C:\Windows\Fonts\consola.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\segoeuib.ttf",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _render_icon(text: str, bg: tuple[int, int, int], fg: tuple[int, int, int] = (255, 255, 255)):
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Almost full-bleed tile so scaled tray icons stay readable.
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=6, fill=bg + (255,))

    max_w, max_h = size - 4, size - 6
    font = _load_font(16)
    for sz in range(46, 14, -1):
        cand = _load_font(sz)
        bbox = draw.textbbox((0, 0), text, font=cand)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if tw <= max_w and th <= max_h:
            font = cand
            break

    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1] - 1
    # Soft outline for contrast on light/dark taskbars after OS scaling.
    draw.text((x, y), text, font=font, fill=fg + (255,), stroke_width=1, stroke_fill=(0, 0, 0, 180))
    return img


def _fmt_power(w: Optional[float]) -> str:
    if w is None:
        return "--"
    if w >= 100:
        return f"{w:.0f}"
    if w >= 10:
        return f"{w:.0f}"
    return f"{w:.1f}"


def _fmt_temp(c: Optional[float]) -> str:
    if c is None:
        return "--"
    return f"{c:.0f}"


def normalize_order(order: Optional[list]) -> list[str]:
    out: list[str] = []
    if order:
        for key in order:
            k = str(key)
            if k in SENSOR_SPECS and k not in out:
                out.append(k)
    for key in DEFAULT_ORDER:
        if key not in out:
            out.append(key)
    return out


class SensorTrayService:
    """
    Four notification-area icons:
      CPU Package power / CPU Package temp / GPU power / GPU temp
    Order is persisted via get_order/save_order (profiles.json settings).
    """

    def __init__(
        self,
        *,
        poll: Callable[[], SensorSnapshot],
        on_show: Optional[Callable[[], None]] = None,
        get_order: Optional[Callable[[], list]] = None,
        save_order: Optional[Callable[[list[str]], None]] = None,
        interval_s: float = 1.5,
    ) -> None:
        self._poll = poll
        self._on_show = on_show
        self._get_order = get_order
        self._save_order = save_order
        self._interval = max(0.8, float(interval_s))
        self._icons: list = []
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self._updater: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._order = list(DEFAULT_ORDER)
        self.last = SensorSnapshot()
        self._running = False

    @property
    def visible(self) -> bool:
        return bool(self._running)

    def set_visible(self, visible: bool) -> bool:
        if visible:
            if self._running:
                return True
            return self.start()
        if self._running:
            self.stop()
        return True

    def start(self) -> bool:
        try:
            import pystray  # noqa: F401
        except Exception:
            return False
        if self._get_order:
            try:
                self._order = normalize_order(self._get_order())
            except Exception:
                self._order = list(DEFAULT_ORDER)
        else:
            self._order = list(DEFAULT_ORDER)
        return self._spawn_icons()

    def stop(self) -> None:
        self._persist_order()
        self._teardown_icons()

    def _persist_order(self) -> None:
        if not self._save_order:
            return
        try:
            self._save_order(list(self._order))
        except Exception:
            pass

    def _teardown_icons(self) -> None:
        self._stop.set()
        self._running = False
        if self._updater and self._updater.is_alive():
            self._updater.join(timeout=2.0)
        self._updater = None
        with self._lock:
            icons = list(self._icons)
            self._icons.clear()
            self._threads.clear()
        for _key, icon, _color, _title in icons:
            try:
                icon.stop()
            except Exception:
                pass

    def _spawn_icons(self) -> bool:
        import pystray

        self._teardown_icons()
        self._stop.clear()
        self._running = True

        def make_show(_icon=None, _item=None):
            if self._on_show:
                self._on_show()

        def make_move(key: str, delta: int):
            def _cb(_icon=None, _item=None):
                self._move_key(key, delta)

            return _cb

        def make_save(_icon=None, _item=None):
            self._persist_order()

        with self._lock:
            for key in self._order:
                title, color = SENSOR_SPECS[key]
                menu = pystray.Menu(
                    pystray.MenuItem("显示主窗口", make_show, default=True),
                    pystray.MenuItem("前移（并保存顺序）", make_move(key, -1)),
                    pystray.MenuItem("后移（并保存顺序）", make_move(key, 1)),
                    pystray.MenuItem("保存当前顺序", make_save),
                )
                # Stable name helps Windows remember tray slot after drag.
                icon = pystray.Icon(
                    f"BladePower.Sensor.{key}",
                    _render_icon("--", color),
                    title,
                    menu,
                )
                self._icons.append((key, icon, color, title))
                t = threading.Thread(target=icon.run, daemon=True, name=f"Tray_{key}")
                self._threads.append(t)
                t.start()

        self._updater = threading.Thread(target=self._loop, daemon=True, name="SensorTrayUpdate")
        self._updater.start()
        self._persist_order()
        return True

    def _move_key(self, key: str, delta: int) -> None:
        order = list(self._order)
        if key not in order:
            return
        i = order.index(key)
        j = i + delta
        if j < 0 or j >= len(order):
            return
        order[i], order[j] = order[j], order[i]
        self._order = order
        self._persist_order()
        # Recreate so OS tray reflects the new registration order.
        threading.Thread(target=self._spawn_icons, daemon=True, name="TrayReorder").start()

    def _loop(self) -> None:
        time.sleep(0.4)
        while not self._stop.is_set():
            try:
                snap = self._poll()
                self.last = snap
                self._apply(snap)
            except Exception:
                pass
            self._stop.wait(self._interval)

    def _apply(self, snap: SensorSnapshot) -> None:
        values = {
            "cpu_pwr": (
                _fmt_power(snap.cpu_power_w),
                f"CPU Package: {snap.cpu_power_w if snap.cpu_power_w is not None else '-'} W",
            ),
            "cpu_tmp": (
                _fmt_temp(snap.cpu_temp_c),
                f"CPU Package: {snap.cpu_temp_c if snap.cpu_temp_c is not None else '-'} °C",
            ),
            "gpu_pwr": (
                _fmt_power(snap.gpu_power_w),
                f"GPU: {snap.gpu_power_w if snap.gpu_power_w is not None else '-'} W",
            ),
            "gpu_tmp": (
                _fmt_temp(snap.gpu_temp_c),
                f"GPU: {snap.gpu_temp_c if snap.gpu_temp_c is not None else '-'} °C",
            ),
        }
        with self._lock:
            icons = list(self._icons)
        for key, icon, color, _base_title in icons:
            text, tip = values[key]
            try:
                icon.icon = _render_icon(text, color)
                icon.title = tip
            except Exception:
                pass
