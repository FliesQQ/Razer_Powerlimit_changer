"""Modern dark ttk theme for BladePower."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

# Teal accent on deep slate — avoid purple / cream AI clichés.
COLORS = {
    "bg": "#0e1218",
    "surface": "#171d27",
    "surface2": "#1e2633",
    "border": "#2c3645",
    "text": "#e6edf5",
    "muted": "#8b98a8",
    "accent": "#1ec8a5",
    "accent_dim": "#149a7e",
    "accent_text": "#041411",
    "danger": "#e57373",
    "warning": "#e0b34d",
    "list_sel": "#1a4d45",
    "status_bg": "#121820",
    "live_bg": "#141a24",
    "input_bg": "#121820",
    "chart_bg": "#121820",
    "chart_grid": "#2a3544",
    "chart_line": "#1ec8a5",
    "chart_point": "#5eead4",
}


def apply_theme(root: tk.Tk) -> ttk.Style:
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    c = COLORS
    root.configure(bg=c["bg"])
    font_ui = ("Segoe UI", 10)
    font_small = ("Segoe UI", 9)
    font_title = ("Segoe UI Semibold", 10)

    style.configure(".", background=c["bg"], foreground=c["text"], font=font_ui)
    style.configure("TFrame", background=c["bg"])
    style.configure("Card.TFrame", background=c["surface"])
    style.configure("Status.TFrame", background=c["status_bg"])

    style.configure("TLabel", background=c["bg"], foreground=c["text"], font=font_ui)
    style.configure(
        "Muted.TLabel", background=c["bg"], foreground=c["muted"], font=font_small
    )
    style.configure(
        "Status.TLabel",
        background=c["status_bg"],
        foreground=c["muted"],
        font=font_small,
    )
    style.configure(
        "Live.TLabel",
        background=c["live_bg"],
        foreground=c["text"],
        font=("Consolas", 9),
    )
    style.configure(
        "Hint.TLabel",
        background=c["bg"],
        foreground=c["warning"],
        font=font_small,
    )
    style.configure(
        "Card.TLabel",
        background=c["surface"],
        foreground=c["text"],
        font=font_ui,
    )

    style.configure(
        "TLabelframe",
        background=c["bg"],
        foreground=c["text"],
        bordercolor=c["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=c["bg"],
        foreground=c["accent"],
        font=font_title,
    )
    style.configure(
        "Live.TLabelframe",
        background=c["live_bg"],
        foreground=c["text"],
        bordercolor=c["border"],
    )
    style.configure(
        "Live.TLabelframe.Label",
        background=c["live_bg"],
        foreground=c["accent"],
        font=font_title,
    )

    style.configure(
        "TButton",
        background=c["surface2"],
        foreground=c["text"],
        bordercolor=c["border"],
        lightcolor=c["surface2"],
        darkcolor=c["border"],
        focuscolor=c["accent_dim"],
        padding=(10, 5),
        font=font_ui,
    )
    style.map(
        "TButton",
        background=[("active", c["border"]), ("pressed", c["accent_dim"])],
        foreground=[("disabled", c["muted"])],
    )
    style.configure(
        "Accent.TButton",
        background=c["accent"],
        foreground=c["accent_text"],
        bordercolor=c["accent_dim"],
        lightcolor=c["accent"],
        darkcolor=c["accent_dim"],
        padding=(12, 6),
        font=("Segoe UI Semibold", 10),
    )
    style.map(
        "Accent.TButton",
        background=[("active", "#2ad4b2"), ("pressed", c["accent_dim"])],
        foreground=[("disabled", c["muted"])],
    )

    style.configure(
        "TCheckbutton",
        background=c["bg"],
        foreground=c["text"],
        focuscolor=c["bg"],
        font=font_ui,
    )
    style.map(
        "TCheckbutton",
        background=[("active", c["bg"])],
        foreground=[("disabled", c["muted"])],
    )
    style.configure(
        "TRadiobutton",
        background=c["bg"],
        foreground=c["text"],
        focuscolor=c["bg"],
        font=font_ui,
    )
    style.map(
        "TRadiobutton",
        background=[("active", c["bg"])],
        foreground=[("disabled", c["muted"])],
    )

    style.configure(
        "TEntry",
        fieldbackground=c["input_bg"],
        foreground=c["text"],
        insertcolor=c["text"],
        bordercolor=c["border"],
        lightcolor=c["border"],
        darkcolor=c["border"],
        padding=4,
    )
    style.map(
        "TEntry",
        fieldbackground=[("disabled", c["surface2"]), ("readonly", c["input_bg"])],
        foreground=[("disabled", c["muted"])],
    )
    style.configure(
        "TCombobox",
        fieldbackground=c["input_bg"],
        background=c["surface2"],
        foreground=c["text"],
        arrowcolor=c["text"],
        bordercolor=c["border"],
        lightcolor=c["border"],
        darkcolor=c["border"],
        insertcolor=c["text"],
        padding=4,
    )
    style.map(
        "TCombobox",
        fieldbackground=[
            ("readonly", c["input_bg"]),
            ("disabled", c["surface2"]),
        ],
        foreground=[
            ("readonly", c["text"]),
            ("disabled", c["muted"]),
        ],
        background=[
            ("active", c["border"]),
            ("readonly", c["surface2"]),
        ],
        arrowcolor=[("disabled", c["muted"])],
        selectbackground=[("readonly", c["list_sel"])],
        selectforeground=[("readonly", c["accent"])],
    )
    # Dropdown list (Windows popdown is a Listbox, not fully covered by Style).
    root.option_add("*TCombobox*Listbox.background", c["input_bg"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", c["list_sel"])
    root.option_add("*TCombobox*Listbox.selectForeground", c["accent"])
    root.option_add("*TCombobox*Listbox.font", font_ui)

    style.configure(
        "TSpinbox",
        fieldbackground=c["input_bg"],
        foreground=c["text"],
        insertcolor=c["text"],
        bordercolor=c["border"],
        arrowcolor=c["text"],
        padding=2,
    )

    style.configure(
        "Horizontal.TScale",
        background=c["bg"],
        troughcolor=c["surface2"],
        bordercolor=c["border"],
        lightcolor=c["accent"],
        darkcolor=c["accent_dim"],
        sliderthickness=18,
    )
    style.map(
        "Horizontal.TScale",
        background=[("active", c["bg"])],
    )
    style.configure(
        "Vertical.TScale",
        background=c["bg"],
        troughcolor=c["surface2"],
        bordercolor=c["border"],
        lightcolor=c["accent"],
        darkcolor=c["accent_dim"],
    )

    style.configure("TNotebook", background=c["bg"], borderwidth=0, tabmargins=(4, 4, 4, 0))
    style.configure(
        "TNotebook.Tab",
        background=c["surface2"],
        foreground=c["muted"],
        padding=(14, 7),
        font=font_ui,
        borderwidth=0,
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", c["surface"]), ("active", c["border"])],
        foreground=[("selected", c["accent"]), ("active", c["text"])],
    )

    style.configure("TSeparator", background=c["border"])
    style.configure(
        "Vertical.TScrollbar",
        background=c["surface2"],
        troughcolor=c["bg"],
        bordercolor=c["border"],
        arrowcolor=c["muted"],
    )
    style.configure(
        "Horizontal.TScrollbar",
        background=c["surface2"],
        troughcolor=c["bg"],
        bordercolor=c["border"],
        arrowcolor=c["muted"],
    )

    return style


def style_listbox(listbox: tk.Listbox) -> None:
    c = COLORS
    listbox.configure(
        bg=c["input_bg"],
        fg=c["text"],
        selectbackground=c["list_sel"],
        selectforeground=c["accent"],
        highlightthickness=1,
        highlightbackground=c["border"],
        highlightcolor=c["accent"],
        relief="flat",
        borderwidth=0,
        activestyle="none",
        font=("Consolas", 9),
    )


def style_canvas(canvas: tk.Canvas, *, dark: bool = True) -> None:
    c = COLORS
    canvas.configure(
        bg=c["surface"] if dark else c["bg"],
        highlightthickness=0,
        borderwidth=0,
    )
