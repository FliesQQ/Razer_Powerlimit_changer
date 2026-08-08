"""Preflight dependency dialog."""

from __future__ import annotations

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from .preflight import Dependency, PreflightReport, download_and_launch_installer, open_download, run_preflight


class PreflightDialog:
    """
    Modal-ish startup check. Returns True if user chose to continue.
    """

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.report: PreflightReport = run_preflight()
        self.continue_app = False
        self._busy = False

        root.title("BladePower - 启动检测")
        root.geometry("760x560")
        root.minsize(700, 480)
        try:
            from .window_icon import apply_window_icon

            apply_window_icon(root)
        except Exception:
            pass

        self.status = tk.StringVar(value="正在检查依赖…")
        self._build()
        self._render()

    def _build(self) -> None:
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            top,
            text="运行前软件 / 硬件检测",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor=tk.W)

        self.compat = tk.Text(top, height=5, wrap=tk.WORD)
        self.compat.pack(fill=tk.X, pady=(6, 8))
        self.compat.configure(state=tk.DISABLED)

        cols = ("状态", "级别", "名称", "说明")
        self.tree = ttk.Treeview(top, columns=cols, show="headings", height=12)
        self.tree.heading("状态", text="状态")
        self.tree.heading("级别", text="级别")
        self.tree.heading("名称", text="名称")
        self.tree.heading("说明", text="说明")
        self.tree.column("状态", width=70, anchor=tk.CENTER)
        self.tree.column("级别", width=80, anchor=tk.CENTER)
        self.tree.column("名称", width=180)
        self.tree.column("说明", width=380)
        self.tree.pack(fill=tk.BOTH, expand=True)

        btns = ttk.Frame(top)
        btns.pack(fill=tk.X, pady=8)
        ttk.Button(btns, text="打开官网下载页", command=self._open_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="下载并启动安装包", command=self._download_selected).pack(side=tk.LEFT, padx=3)
        ttk.Button(btns, text="重新检测", command=self._recheck).pack(side=tk.LEFT, padx=3)

        ttk.Label(top, textvariable=self.status, wraplength=720).pack(anchor=tk.W, pady=(0, 6))

        bottom = ttk.Frame(top)
        bottom.pack(fill=tk.X)
        ttk.Button(bottom, text="退出", command=self._quit).pack(side=tk.RIGHT, padx=3)
        ttk.Button(
            bottom, text="继续启用（不再显示）", command=self._continue_and_hide
        ).pack(side=tk.RIGHT, padx=3)
        self.btn_continue = ttk.Button(bottom, text="继续启动", command=self._continue)
        self.btn_continue.pack(side=tk.RIGHT, padx=3)

        note = (
            "说明：WinRing0 随本工具分发，勿从不明来源下载。"
            "雷云 Synapse 不是必需；Intel XTU / Afterburner 为可选。"
            "「下载并启动安装包」仅对提供直链的项目可用（如 Afterburner ZIP）。"
        )
        ttk.Label(top, text=note, wraplength=720, foreground="#444").pack(anchor=tk.W, pady=(8, 0))

    def _level_cn(self, level: str) -> str:
        return {"required": "必需", "recommended": "建议", "optional": "可选"}.get(level, level)

    def _render(self) -> None:
        self.compat.configure(state=tk.NORMAL)
        self.compat.delete("1.0", tk.END)
        cpu = self.report.cpu_vendor or "-"
        self.compat.insert(
            tk.END,
            f"CPU: {cpu}\n{self.report.device_summary}",
        )
        self.compat.configure(state=tk.DISABLED)

        for i in self.tree.get_children():
            self.tree.delete(i)
        self._rows: list[Dependency] = list(self.report.items)
        for dep in self._rows:
            self.tree.insert(
                "",
                tk.END,
                iid=dep.id,
                values=(
                    "OK" if dep.ok else "缺失",
                    self._level_cn(dep.level.value if hasattr(dep.level, "value") else str(dep.level)),
                    dep.name,
                    dep.detail,
                ),
            )

        if self.report.can_continue:
            self.status.set("必需项已满足，可以继续。缺失的可选项不影响基础功能。")
            self.btn_continue.state(["!disabled"])
        else:
            self.status.set(
                "缺少必需项: "
                + "、".join(self.report.blockers)
                + "。请处理后点「重新检测」，或仍可强制继续（功能降级）。"
            )
            self.btn_continue.state(["!disabled"])

    def _selected_dep(self) -> Optional[Dependency]:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一行依赖")
            return None
        dep_id = sel[0]
        for d in self._rows:
            if d.id == dep_id:
                return d
        return None

    def _open_selected(self) -> None:
        dep = self._selected_dep()
        if not dep:
            return
        if not dep.download_url:
            messagebox.showinfo("提示", f"「{dep.name}」无官网链接（可能已随程序附带）")
            return
        open_download(dep)
        self.status.set(f"已打开下载页: {dep.name}")

    def _download_selected(self) -> None:
        dep = self._selected_dep()
        if not dep:
            return
        if not dep.installer_url:
            if dep.download_url:
                if messagebox.askyesno("无直链", f"「{dep.name}」无自动安装直链，是否打开官网？"):
                    open_download(dep)
            else:
                messagebox.showinfo("提示", "该项不支持自动下载")
            return
        if self._busy:
            return
        if not messagebox.askyesno(
            "确认",
            f"将从厂商地址下载「{dep.name}」安装包并启动/打开。\n继续？",
        ):
            return

        self._busy = True
        self.status.set(f"正在下载 {dep.name}…")

        def work():
            try:
                path = download_and_launch_installer(dep, progress=lambda m: self.root.after(0, lambda: self.status.set(m)))
                self.root.after(0, lambda: self.status.set(f"已处理: {path}"))
            except Exception as exc:  # noqa: BLE001
                self.root.after(0, lambda: messagebox.showerror("下载失败", str(exc)))
            finally:
                self._busy = False

        threading.Thread(target=work, daemon=True).start()

    def _recheck(self) -> None:
        self.status.set("重新检测中…")
        self.report = run_preflight()
        self._render()

    def _continue(self) -> None:
        if not self._confirm_if_blocked():
            return
        self.continue_app = True
        self.root.quit()

    def _continue_and_hide(self) -> None:
        if not self._confirm_if_blocked():
            return
        _set_skip_preflight(True)
        self.continue_app = True
        self.root.quit()

    def _confirm_if_blocked(self) -> bool:
        if not self.report.can_continue:
            return bool(
                messagebox.askyesno(
                    "缺少必需项",
                    "仍有必需项缺失，继续将导致部分功能不可用。确定继续？",
                )
            )
        return True

    def _quit(self) -> None:
        self.continue_app = False
        self.root.quit()


def _load_settings() -> dict:
    import json

    from .paths import profiles_path

    path = profiles_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return dict(data.get("settings") or {})
    except Exception:
        return {}


def _save_setting(**kwargs) -> None:
    import json

    from .paths import profiles_path

    path = profiles_path()
    data: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    settings = dict(data.get("settings") or {})
    settings.update(kwargs)
    data["settings"] = settings
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _set_skip_preflight(skip: bool) -> None:
    _save_setting(skip_preflight=bool(skip))


def is_preflight_skipped() -> bool:
    return bool(_load_settings().get("skip_preflight"))


def show_preflight(*, force: bool = False) -> bool:
    if not force and is_preflight_skipped():
        return True
    root = tk.Tk()
    dlg = PreflightDialog(root)
    root.protocol("WM_DELETE_WINDOW", dlg._quit)
    root.mainloop()
    root.destroy()
    return bool(dlg.continue_app)
